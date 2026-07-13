import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.backend import ticket_vectors
from app.backend.database import KbArticleRecord, TicketCommentRecord, TicketRecord


class TicketVectorEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_upsert_marks_source_only_evidence_version_two(self):
        ticket = TicketRecord(
            id="ticket-v2",
            subject="Printer unavailable",
            description="The requester reports a paper jam.",
            summary="Generated summary",
            ai_reasoning="Generated reasoning",
        )
        with patch.object(
            ticket_vectors,
            "_upsert_document",
            new=AsyncMock(return_value=True),
        ) as upsert:
            changed = await ticket_vectors.upsert_ticket_document(
                MagicMock(), ticket
            )

        self.assertTrue(changed)
        self.assertEqual(upsert.await_args.kwargs["body"], ticket.description)
        self.assertEqual(
            upsert.await_args.kwargs["metadata"]["evidence_version"], 2
        )

    async def test_retrieval_defense_rejects_legacy_ticket_documents(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = [
            SimpleNamespace(
                source_type="ticket",
                source_id="legacy-ticket",
                ticket_id="legacy-ticket",
                title="Printer paper jam",
                body="Printer paper jam from a generated legacy summary.",
                metadata_json="{}",
            ),
            SimpleNamespace(
                source_type="ticket",
                source_id="source-ticket",
                ticket_id="source-ticket",
                title="Printer paper jam",
                body="The requester reports a printer paper jam.",
                metadata_json='{"evidence_version": 2}',
            ),
        ]

        with (
            patch.object(
                ticket_vectors, "ticket_vector_store_ready", return_value=True
            ),
            patch.object(ticket_vectors, "embedding_enabled", return_value=False),
        ):
            result = await ticket_vectors.retrieve_ticket_context(
                db,
                "printer paper jam",
                source_types=["ticket"],
            )

        self.assertEqual(
            [item["source_id"] for item in result["results"]],
            ["source-ticket"],
        )

    async def test_repeated_backfills_cover_more_than_one_legacy_page(self):
        remaining = [
            TicketRecord(
                id=f"legacy-{index:04d}",
                subject=f"Legacy ticket {index}",
                description="Original requester evidence",
            )
            for index in range(600)
        ]
        seen: list[str] = []

        def legacy_batch(_db, limit):
            return remaining[:limit]

        async def upsert(_db, ticket, force=False):
            seen.append(ticket.id)
            remaining.remove(ticket)
            return True

        with (
            patch.object(
                ticket_vectors, "ticket_vector_store_ready", return_value=True
            ),
            patch.object(
                ticket_vectors,
                "private_comment_indexing_enabled",
                return_value=True,
            ),
            patch.object(
                ticket_vectors,
                "_legacy_ticket_backfill_batch",
                side_effect=legacy_batch,
            ),
            patch.object(
                ticket_vectors, "upsert_ticket_document", side_effect=upsert
            ),
        ):
            first = await ticket_vectors.backfill_ticket_documents(
                MagicMock(),
                limit=500,
                include_comments=False,
                include_kb=False,
            )
            second = await ticket_vectors.backfill_ticket_documents(
                MagicMock(),
                limit=500,
                include_comments=False,
                include_kb=False,
            )

        self.assertEqual(first["tickets_seen"], 500)
        self.assertEqual(second["tickets_seen"], 100)
        self.assertEqual(len(seen), 600)
        self.assertEqual(len(set(seen)), 600)
        self.assertEqual(remaining, [])

    async def test_repeated_backfills_cover_new_store_for_all_source_types(self):
        remaining_tickets = [
            TicketRecord(id=f"ticket-{index:04d}", subject="New ticket")
            for index in range(600)
        ]
        remaining_comments = [
            TicketCommentRecord(
                id=index + 1,
                ticket_id=f"ticket-{index:04d}",
                body="Public evidence",
                is_private=False,
            )
            for index in range(600)
        ]
        remaining_articles = [
            KbArticleRecord(
                id=f"article-{index:04d}",
                title="Published evidence",
                slug=f"article-{index:04d}",
                status="published",
            )
            for index in range(600)
        ]

        async def upsert_ticket(_db, ticket, force=False):
            remaining_tickets.remove(ticket)
            return True

        async def upsert_comment(_db, comment, force=False):
            remaining_comments.remove(comment)
            return True

        async def upsert_article(_db, article, force=False):
            remaining_articles.remove(article)
            return True

        with (
            patch.object(
                ticket_vectors, "ticket_vector_store_ready", return_value=True
            ),
            patch.object(
                ticket_vectors,
                "private_comment_indexing_enabled",
                return_value=True,
            ),
            patch.object(
                ticket_vectors,
                "_legacy_ticket_backfill_batch",
                return_value=[],
            ),
            patch.object(
                ticket_vectors,
                "_missing_ticket_backfill_batch",
                side_effect=lambda _db, limit: remaining_tickets[:limit],
            ),
            patch.object(
                ticket_vectors,
                "_missing_comment_backfill_batch",
                side_effect=lambda _db, limit, include_private: remaining_comments[:limit],
            ),
            patch.object(
                ticket_vectors,
                "_missing_kb_backfill_batch",
                side_effect=lambda _db, limit: remaining_articles[:limit],
            ),
            patch.object(
                ticket_vectors,
                "upsert_ticket_document",
                side_effect=upsert_ticket,
            ),
            patch.object(
                ticket_vectors,
                "upsert_comment_document",
                side_effect=upsert_comment,
            ),
            patch.object(
                ticket_vectors,
                "upsert_kb_document",
                side_effect=upsert_article,
            ),
        ):
            first = await ticket_vectors.backfill_ticket_documents(
                MagicMock(), limit=500
            )
            second = await ticket_vectors.backfill_ticket_documents(
                MagicMock(), limit=500
            )

        self.assertEqual(
            (first["tickets_seen"], first["comments_seen"], first["kb_seen"]),
            (500, 500, 500),
        )
        self.assertEqual(
            (second["tickets_seen"], second["comments_seen"], second["kb_seen"]),
            (100, 100, 100),
        )
        self.assertEqual(remaining_tickets, [])
        self.assertEqual(remaining_comments, [])
        self.assertEqual(remaining_articles, [])

    def test_legacy_backfill_batch_preserves_queue_order(self):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [
            "legacy-b",
            "legacy-a",
        ]
        legacy_a = TicketRecord(id="legacy-a", subject="A")
        legacy_b = TicketRecord(id="legacy-b", subject="B")
        db.query.return_value.filter.return_value.all.return_value = [
            legacy_a,
            legacy_b,
        ]

        batch = ticket_vectors._legacy_ticket_backfill_batch(db, 25)

        self.assertEqual([ticket.id for ticket in batch], ["legacy-b", "legacy-a"])
        self.assertEqual(db.execute.call_args.args[1], {"limit": 25})
        query = str(db.execute.call_args.args[0])
        self.assertIn("evidence_version", query)

    def test_legacy_backfill_batch_removes_orphaned_search_artifacts(self):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [
            "orphaned-ticket"
        ]
        db.query.return_value.filter.return_value.all.return_value = []

        batch = ticket_vectors._legacy_ticket_backfill_batch(db, 25)

        self.assertEqual(batch, [])
        self.assertEqual(db.execute.call_count, 2)
        delete_call = db.execute.call_args_list[1]
        self.assertIn("DELETE FROM ticket_search_documents", str(delete_call.args[0]))
        self.assertEqual(
            delete_call.args[1], {"source_ids": ["orphaned-ticket"]}
        )
        db.commit.assert_called_once()

    def test_missing_source_batches_only_select_absent_documents(self):
        ticket_db = MagicMock()
        ticket_db.execute.return_value.scalars.return_value.all.return_value = ["t-2"]
        ticket = TicketRecord(id="t-2", subject="Ticket")
        ticket_db.query.return_value.filter.return_value.all.return_value = [ticket]

        comment_db = MagicMock()
        comment_db.execute.return_value.scalars.return_value.all.return_value = ["2"]
        comment = TicketCommentRecord(id=2, ticket_id="t-2", body="Comment")
        comment_db.query.return_value.filter.return_value.all.return_value = [comment]

        article_db = MagicMock()
        article_db.execute.return_value.scalars.return_value.all.return_value = ["kb-2"]
        article = KbArticleRecord(
            id="kb-2", title="Article", slug="kb-2", status="published"
        )
        article_db.query.return_value.filter.return_value.all.return_value = [article]

        tickets = ticket_vectors._missing_ticket_backfill_batch(ticket_db, 50)
        comments = ticket_vectors._missing_comment_backfill_batch(
            comment_db, 50, include_private=False
        )
        articles = ticket_vectors._missing_kb_backfill_batch(article_db, 50)

        self.assertEqual(tickets, [ticket])
        self.assertEqual(comments, [comment])
        self.assertEqual(articles, [article])
        for db in (ticket_db, comment_db, article_db):
            query = str(db.execute.call_args.args[0])
            self.assertIn("LEFT JOIN ticket_search_documents", query)
            self.assertIn("document.source_id IS NULL", query)
        comment_query = str(comment_db.execute.call_args.args[0])
        self.assertIn("source_comment.is_private", comment_query)
        article_query = str(article_db.execute.call_args.args[0])
        self.assertIn("source_article.status = 'published'", article_query)

    def test_status_reports_ticket_documents_needing_v2_backfill(self):
        db = MagicMock()
        db.execute.return_value.first.return_value = SimpleNamespace(
            documents=8,
            embedded_documents=6,
            stale_documents=2,
            legacy_ticket_documents=3,
            missing_ticket_documents=4,
            missing_comment_documents=5,
            missing_kb_documents=6,
        )
        with (
            patch.object(
                ticket_vectors, "ticket_vector_store_ready", return_value=True
            ),
            patch.object(ticket_vectors, "embedding_enabled", return_value=True),
            patch.object(
                ticket_vectors,
                "embedding_model",
                return_value="openai/test-embedding",
            ),
            patch.object(ticket_vectors, "_dimensions", return_value=1536),
            patch.object(
                ticket_vectors,
                "_embedding_identity",
                return_value="embedding-provider-v1:current",
            ),
        ):
            status = ticket_vectors.ticket_vector_status(db)

        self.assertEqual(status["documents"], 8)
        self.assertEqual(status["legacy_ticket_documents"], 3)
        self.assertEqual(status["missing_ticket_documents"], 4)
        self.assertEqual(status["missing_comment_documents"], 5)
        self.assertEqual(status["missing_kb_documents"], 6)
        query = str(db.execute.call_args.args[0])
        self.assertIn("source_type = 'ticket'", query)
        self.assertIn("evidence_version", query)
        self.assertIn("LEFT JOIN ticket_search_documents", query)
        self.assertEqual(
            db.execute.call_args.args[1],
            {
                "include_private_comments": False,
                "embedding_identity": "embedding-provider-v1:current",
            },
        )

    def test_unavailable_store_preserves_status_shape_with_zero_legacy_count(self):
        db = MagicMock()
        with patch.object(
            ticket_vectors, "ticket_vector_store_ready", return_value=False
        ):
            status = ticket_vectors.ticket_vector_status(db)

        self.assertFalse(status["vector_store_ready"])
        self.assertEqual(status["legacy_ticket_documents"], 0)
        self.assertEqual(status["missing_ticket_documents"], 0)
        self.assertEqual(status["missing_comment_documents"], 0)
        self.assertEqual(status["missing_kb_documents"], 0)
        db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
