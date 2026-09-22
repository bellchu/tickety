import asyncio
import contextlib
import importlib
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.backend.rag import chunking, config, embedding_worker, retrieval_v2, snapshots, store_v2


def _row(
    chunk_id: str,
    *,
    source_type: str = "ticket",
    source_id: str = "ticket-1",
    ticket_id: str | None = "ticket-1",
    content: str = "Evidence text",
    chunk_index: int = 0,
):
    metadata = {
        "display_title": "Evidence",
        "external_source": "manual",
        "status": "Open",
        "reviewer_id": "reviewer" if source_type == "kb_article" else None,
    }
    return {
        "chunk_id": chunk_id,
        "scope_key": "default",
        "source_type": source_type,
        "source_id": source_id,
        "ticket_id": ticket_id,
        "chunk_index": chunk_index,
        "section_path": "Evidence",
        "content": content,
        "content_hash": f"content-{chunk_id}",
        "parent_hash": f"parent-{source_id}",
        "source_revision": "1",
        "metadata_json": metadata,
        "authoritative_external_source": "manual" if source_type == "ticket" else None,
        "signal_score": 0.99,
    }


class RagV2ChunkingTests(unittest.TestCase):
    def test_chunking_is_deterministic_and_bounded(self):
        body = "\n\n".join(
            f"## Section {index}\n" + ("printer network timeout. " * 80)
            for index in range(5)
        )
        first = chunking.chunk_source("Runbook", body, max_chunks=128)
        second = chunking.chunk_source("Runbook", body, max_chunks=128)
        encoder = chunking._encoding()

        self.assertEqual(first, second)
        self.assertGreater(len(first), 1)
        self.assertTrue(all(len(encoder.encode(item.content)) <= 600 for item in first))
        self.assertTrue(all(item.section_path.startswith("Runbook") for item in first))

    def test_oversized_source_fails_without_silent_truncation(self):
        body = "\n\n".join(f"paragraph {index} " + ("x " * 500) for index in range(4))
        with self.assertRaises(chunking.SourceTooLargeError):
            chunking.chunk_source(
                "Oversized",
                body,
                max_chunks=1,
                target_tokens=100,
                maximum_tokens=120,
                overlap_tokens=10,
            )

    def test_chunk_identity_changes_with_parent_or_chunker(self):
        baseline = chunking.chunk_id("default", "ticket", "1", "parent-a", 0, "v1")
        self.assertNotEqual(
            baseline,
            chunking.chunk_id("default", "ticket", "1", "parent-b", 0, "v1"),
        )
        self.assertNotEqual(
            baseline,
            chunking.chunk_id("default", "ticket", "1", "parent-a", 0, "v2"),
        )


class RagV2RetrievalTests(unittest.TestCase):
    def test_rrf_rewards_presence_in_both_signals_and_is_stable(self):
        lexical = [_row("lexical-only"), _row("both", source_id="ticket-2", ticket_id="ticket-2")]
        vector = [_row("both", source_id="ticket-2", ticket_id="ticket-2"), _row("vector-only")]
        fused = retrieval_v2.reciprocal_rank_fusion({
            "lexical_non_kb": lexical,
            "vector_non_kb": vector,
        })

        self.assertEqual(fused[0]["chunk_id"], "both")
        self.assertEqual(fused[0]["match_method"], "hybrid")
        self.assertEqual(
            fused,
            retrieval_v2.reciprocal_rank_fusion({
                "lexical_non_kb": lexical,
                "vector_non_kb": vector,
            }),
        )

    def test_diversity_caps_parent_and_reserves_approved_kb(self):
        ranked = [
            {**retrieval_v2._shape(_row(f"t-{index}", chunk_index=index)), "score": 1 - index / 10, "match_method": "lexical"}
            for index in range(3)
        ]
        ranked.extend([
            {**retrieval_v2._shape(_row("other", source_id="ticket-2", ticket_id="ticket-2")), "score": 0.6, "match_method": "lexical"},
            {**retrieval_v2._shape(_row("kb", source_type="kb_article", source_id="kb-1", ticket_id=None)), "score": 0.5, "match_method": "lexical"},
        ])

        selected = retrieval_v2.diversify(ranked, 3)

        self.assertLessEqual(
            sum(item["source_id"] == "ticket-1" for item in selected), 2
        )
        self.assertTrue(any(item["authority"] == "published_kb" for item in selected))

    def test_query_cache_key_is_normalized_scoped_and_hash_only(self):
        identity = "embedding-provider-v1:test"
        first = retrieval_v2.query_hash("  Printer\n timeout ", identity, "scope-a")
        second = retrieval_v2.query_hash("Printer timeout", identity, "scope-a")
        other_scope = retrieval_v2.query_hash("Printer timeout", identity, "scope-b")

        self.assertEqual(first, second)
        self.assertNotEqual(first, other_scope)
        self.assertNotIn("Printer", first)
        self.assertEqual(len(first), 64)


class RagV2WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_item_isolated_without_discarding_valid_siblings(self):
        rows = [
            {"content": "good-a"},
            {"content": "toxic"},
            {"content": "good-b"},
        ]

        async def embed(inputs):
            if "toxic" in inputs:
                raise ValueError("invalid item")
            return [[float(index)] * 3 for index, _value in enumerate(inputs)]

        with patch.object(embedding_worker, "_embed_texts", new=embed):
            succeeded, failed = await embedding_worker._embed_with_isolation(rows)

        self.assertEqual([row["content"] for row, _vector in succeeded], ["good-a", "good-b"])
        self.assertEqual([row["content"] for row in failed], ["toxic"])

    async def test_isolation_renews_progress_at_each_bounded_provider_return(self):
        rows = [{"content": f"item-{index}"} for index in range(4)]
        elapsed_seconds = 0
        progress_at = []

        async def embed(inputs):
            nonlocal elapsed_seconds
            # Every provider call returns inside its configured bound, but a
            # poisoned batch legitimately fans out into a long isolation tree.
            elapsed_seconds += 70
            if len(inputs) > 1:
                raise ValueError("split this batch")
            return [[1.0, 2.0, 3.0]]

        with patch.object(embedding_worker, "_embed_texts", new=embed):
            succeeded, failed = await embedding_worker._embed_with_isolation(
                rows,
                on_progress=lambda: progress_at.append(elapsed_seconds),
            )

        self.assertEqual(len(succeeded), 4)
        self.assertEqual(failed, [])
        self.assertGreater(elapsed_seconds, 120)
        # The old outer-cycle heartbeat would first renew only at 490 seconds,
        # exceeding the old 120-second health budget. The new marker renews
        # exclusively after each returned bounded provider suboperation.
        self.assertLessEqual(
            max(
                current - previous
                for previous, current in zip([0, *progress_at], progress_at)
            ),
            70,
        )

    async def test_blocked_provider_call_cannot_renew_progress(self):
        never_returns = asyncio.Event()
        progress = []

        async def embed(_inputs):
            await never_returns.wait()
            return []

        with patch.object(embedding_worker, "_embed_texts", new=embed):
            task = asyncio.create_task(
                embedding_worker._embed_with_isolation(
                    [{"content": "blocked"}], on_progress=progress.append
                )
            )
            await asyncio.sleep(0)
            self.assertEqual(progress, [])
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


class RagV2ConfigurationAndSnapshotTests(unittest.TestCase):
    def test_ineligible_chunk_cursor_key_is_scope_isolated_and_fits_schema_meta(self):
        first = store_v2._ineligible_chunk_cursor_key("tenant-a")
        second = store_v2._ineligible_chunk_cursor_key("tenant-b")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("chunk_purge:"))
        self.assertLessEqual(len(first), 80)

    def test_ineligible_chunk_recovery_pages_before_policy_delete_and_queues_sources(self):
        db = MagicMock()
        cursor = MagicMock()
        cursor.one.return_value = SimpleNamespace(
            value='{"chunk_id":"chunk-before","source_id":"ticket-before","source_type":"ticket"}'
        )
        candidates = MagicMock()
        candidates.all.return_value = [
            SimpleNamespace(chunk_id="chunk-a", source_type="comment", source_id="7"),
            SimpleNamespace(chunk_id="chunk-b", source_type="ticket", source_id="ticket-a"),
        ]
        deleted = MagicMock()
        deleted.all.return_value = [SimpleNamespace(source_type="ticket", source_id="ticket-a")]
        db.execute.side_effect = [MagicMock(), cursor, candidates, deleted, MagicMock(), MagicMock()]
        intents = [SimpleNamespace(source_type="ticket", source_id="ticket-a")]

        with (
            patch.object(store_v2, "store_ready", return_value=True),
            patch.object(store_v2, "scope_key", return_value="tenant-a"),
            patch.object(store_v2, "_private_comment_indexing_enabled", return_value=False),
            patch.object(
                store_v2,
                "_commit_source_change_with_snapshot_purge_queue",
                return_value=intents,
            ) as queued,
            patch.object(store_v2, "_drain_source_snapshot_purge_queue") as drained,
        ):
            count = store_v2.purge_ineligible_chunks(db, max_rows=999_999)

        self.assertEqual(count, 1)
        candidate_query = str(db.execute.call_args_list[2].args[0])
        self.assertIn("(source_type, source_id, chunk_id) >", candidate_query)
        self.assertIn("ORDER BY source_type, source_id, chunk_id", candidate_query)
        self.assertIn("LIMIT :limit", candidate_query)
        self.assertEqual(db.execute.call_args_list[2].args[1]["limit"], 5_000)
        delete_query = str(db.execute.call_args_list[3].args[0])
        self.assertIn("chunk.chunk_id = ANY(:candidate_ids)", delete_query)
        self.assertIn("chunk.source_type = 'ticket'", delete_query)
        self.assertIn("chunk.source_type = 'comment'", delete_query)
        self.assertIn("chunk.source_type = 'kb_article'", delete_query)
        self.assertEqual(
            db.execute.call_args_list[3].args[1]["candidate_ids"],
            ["chunk-a", "chunk-b"],
        )
        self.assertFalse(db.execute.call_args_list[3].args[1]["include_private_comments"])
        self.assertEqual(
            db.execute.call_args_list[5].args[1]["value"],
            '{"chunk_id":"chunk-b","source_id":"ticket-a","source_type":"ticket"}',
        )
        queued.assert_called_once_with(db, [("ticket", "ticket-a")])
        drained.assert_called_once_with(db, intents)

    def test_ineligible_chunk_recovery_resets_only_after_a_bounded_page_end(self):
        db = MagicMock()
        cursor = MagicMock()
        cursor.one.return_value = SimpleNamespace(value="broken-cursor")
        candidates = MagicMock()
        candidates.all.return_value = []
        db.execute.side_effect = [MagicMock(), cursor, candidates, MagicMock()]

        with (
            patch.object(store_v2, "store_ready", return_value=True),
            patch.object(store_v2, "scope_key", return_value="tenant-a"),
        ):
            count = store_v2.purge_ineligible_chunks(db, max_rows=7)

        self.assertEqual(count, 0)
        candidate_query = str(db.execute.call_args_list[2].args[0])
        self.assertIn("ORDER BY source_type, source_id, chunk_id", candidate_query)
        self.assertIn("LIMIT :limit", candidate_query)
        self.assertNotIn("(source_type, source_id, chunk_id) >", candidate_query)
        self.assertEqual(db.execute.call_args_list[2].args[1]["limit"], 7)
        reset_query = str(db.execute.call_args_list[3].args[0])
        self.assertIn("SET value = '{}'", reset_query)
        db.commit.assert_called_once()

    def test_ineligible_chunk_recovery_rolls_back_delete_and_cursor_when_queueing_fails(self):
        db = MagicMock()
        cursor = MagicMock()
        cursor.one.return_value = SimpleNamespace(value="{}")
        candidates = MagicMock()
        candidates.all.return_value = [
            SimpleNamespace(chunk_id="chunk-a", source_type="ticket", source_id="ticket-a"),
        ]
        deleted = MagicMock()
        deleted.all.return_value = [SimpleNamespace(source_type="ticket", source_id="ticket-a")]
        db.execute.side_effect = [MagicMock(), cursor, candidates, deleted, MagicMock(), MagicMock()]

        with (
            patch.object(store_v2, "store_ready", return_value=True),
            patch.object(store_v2, "scope_key", return_value="tenant-a"),
            patch.object(store_v2, "_private_comment_indexing_enabled", return_value=False),
            patch.object(
                store_v2,
                "_commit_source_change_with_snapshot_purge_queue",
                side_effect=RuntimeError("queue unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "queue unavailable"),
        ):
            store_v2.purge_ineligible_chunks(db, max_rows=1)

        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_source_snapshot_purge_is_indexed_and_has_a_total_batch_limit(self):
        db = MagicMock()
        selected = MagicMock()
        selected.all.return_value = [
            SimpleNamespace(snapshot_id="snapshot-a"),
            SimpleNamespace(snapshot_id="snapshot-b"),
        ]
        deleted = MagicMock()
        deleted.rowcount = 2
        db.execute.side_effect = [selected, deleted]

        with patch.object(snapshots, "store_ready", return_value=True):
            count = snapshots.purge_snapshots_for_sources(
                db, [("ticket", "ticket-a")], max_rows=2
            )

        self.assertEqual(count, 2)
        query = str(db.execute.call_args_list[0].args[0])
        self.assertIn("rag_context_snapshot_sources_v2", query)
        self.assertNotIn("chunk_manifest_json", query)
        self.assertEqual(db.execute.call_args_list[0].args[1]["limit"], 2)
        db.commit.assert_called_once()

    def test_full_source_snapshot_purge_uses_independently_committed_batches(self):
        db = MagicMock()
        with patch.object(snapshots, "purge_snapshots_for_sources", side_effect=[2, 2, 1]) as purge:
            self.assertEqual(
                snapshots.purge_all_snapshots_for_sources(
                    db, [("ticket", "ticket-a")], batch_size=2
                ),
                5,
            )

        self.assertEqual(purge.call_count, 3)
        for call in purge.call_args_list:
            self.assertEqual(call.kwargs["max_rows"], 2)

    def test_ineligible_snapshot_recovery_is_indexed_bounded_and_committed(self):
        db = MagicMock()
        cursor = MagicMock()
        cursor.one.return_value = SimpleNamespace(
            value='{"created_at":"2025-12-31T23:59:59","id":"snapshot-before"}'
        )
        candidates = MagicMock()
        candidates.all.return_value = [
            SimpleNamespace(id="snapshot-a", created_at=datetime(2026, 1, 1, 0, 0, 0)),
            SimpleNamespace(id="snapshot-b", created_at=datetime(2026, 1, 1, 0, 0, 1)),
        ]
        deleted = MagicMock()
        deleted.rowcount = 2
        db.execute.side_effect = [MagicMock(), cursor, candidates, deleted, MagicMock()]

        with (
            patch.object(snapshots, "store_ready", return_value=True),
            patch("app.backend.rag.store_v2._private_comment_indexing_enabled", return_value=False),
        ):
            count = snapshots.purge_ineligible_snapshots(db, max_rows=999_999)

        self.assertEqual(count, 2)
        queries = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("FOR UPDATE", queries[1])
        self.assertIn("(created_at, id) >", queries[2])
        self.assertIn("ORDER BY created_at, id", queries[2])
        self.assertIn("LIMIT :limit", queries[2])
        self.assertNotIn(" OR ", queries[2])
        self.assertNotIn("CAST(:cursor_created_at", queries[2])
        self.assertIn("rag_context_snapshot_sources_v2", queries[3])
        self.assertIn("ANY(:candidate_ids)", queries[3])
        self.assertIn("comment.id = CASE", queries[3])
        self.assertIn("^(0|[1-9][0-9]{0,9})$", queries[3])
        self.assertNotIn("CAST(comment.id AS text)", queries[3])
        self.assertEqual(db.execute.call_args_list[2].args[1]["limit"], 5_000)
        self.assertEqual(
            db.execute.call_args_list[2].args[1]["cursor_created_at"],
            datetime(2025, 12, 31, 23, 59, 59),
        )
        self.assertEqual(db.execute.call_args_list[2].args[1]["cursor_id"], "snapshot-before")
        self.assertFalse(db.execute.call_args_list[3].args[1]["include_private_comments"])
        self.assertEqual(db.execute.call_args_list[3].args[1]["candidate_ids"], ["snapshot-a", "snapshot-b"])
        self.assertEqual(
            db.execute.call_args_list[4].args[1]["cursor"],
            '{"created_at":"2026-01-01T00:00:01","id":"snapshot-b"}',
        )
        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    def test_ineligible_snapshot_recovery_resets_cursor_after_bounded_page_end(self):
        db = MagicMock()
        cursor = MagicMock()
        cursor.one.return_value = SimpleNamespace(value="snapshot-last")
        candidates = MagicMock()
        candidates.all.return_value = []
        db.execute.side_effect = [MagicMock(), cursor, candidates, MagicMock()]

        with patch.object(snapshots, "store_ready", return_value=True):
            count = snapshots.purge_ineligible_snapshots(db, max_rows=10)

        self.assertEqual(count, 0)
        self.assertEqual(db.execute.call_count, 4)
        candidate_query = str(db.execute.call_args_list[2].args[0])
        self.assertNotIn("(created_at, id) >", candidate_query)
        self.assertNotIn(" OR ", candidate_query)
        self.assertNotIn("CAST(:cursor_created_at", candidate_query)
        self.assertEqual(
            db.execute.call_args_list[2].args[1],
            {"limit": 10},
        )
        reset_query = str(db.execute.call_args_list[3].args[0])
        self.assertIn("SET value = '{}'", reset_query)
        db.commit.assert_called_once()

    def test_pending_source_purge_recovers_after_replacement_commit(self):
        db = MagicMock()
        listed = MagicMock()
        listed.all.return_value = [SimpleNamespace(
            key="snapshot_purge:abc",
            value='{"source_type":"ticket","source_id":"ticket-a"}',
        )]
        db.execute.return_value = listed
        with (
            patch.object(snapshots, "store_ready", return_value=True),
            patch.object(snapshots, "purge_all_snapshots_for_sources", return_value=2) as purge,
        ):
            completed = snapshots.drain_pending_source_snapshot_purges(db, max_rows=1)

        self.assertEqual(completed, 1)
        purge.assert_called_once_with(db, [("ticket", "ticket-a")])
        self.assertEqual(db.execute.call_args_list[-1].args[1]["key"], "snapshot_purge:abc")
        self.assertEqual(
            db.execute.call_args_list[-1].args[1]["expected_value"],
            '{"source_type":"ticket","source_id":"ticket-a"}',
        )
        db.commit.assert_called_once()

    def test_pending_source_purge_keeps_newer_same_source_intent(self):
        """An old drain must not erase a mutation committed while it purges."""
        db = MagicMock()
        old_value = '{"nonce":"old","source_id":"ticket-a","source_type":"ticket"}'
        listed = MagicMock()
        listed.all.return_value = [SimpleNamespace(
            key="snapshot_purge:abc", value=old_value,
        )]
        db.execute.return_value = listed

        def publish_newer_intent(_db, _sources):
            # This models another replica committing a later mutation after
            # this drainer read ``old_value`` but before it clears the key.
            snapshots.queue_source_snapshot_purge(
                db, [("ticket", "ticket-a")]
            )
            return 1

        with (
            patch.object(snapshots, "store_ready", return_value=True),
            patch.object(
                snapshots,
                "purge_all_snapshots_for_sources",
                side_effect=publish_newer_intent,
            ),
            patch.object(snapshots.uuid, "uuid4", return_value="new"),
        ):
            completed = snapshots.drain_pending_source_snapshot_purges(db, max_rows=1)

        self.assertEqual(completed, 1)
        clear_params = db.execute.call_args_list[-1].args[1]
        self.assertEqual(clear_params["key"], "snapshot_purge:abc")
        self.assertEqual(clear_params["expected_value"], old_value)
        clear_query = str(db.execute.call_args_list[-1].args[0])
        self.assertIn("value = :expected_value", clear_query)
        queued_params = db.execute.call_args_list[-2].args[1]
        self.assertNotEqual(queued_params["value"], old_value)

    def test_invalid_pending_source_purge_is_cleared_without_poisoning_recovery(self):
        db = MagicMock()
        listed = MagicMock()
        listed.all.return_value = [SimpleNamespace(
            key="snapshot_purge:broken", value="not-json",
        )]
        db.execute.return_value = listed
        with (
            patch.object(snapshots, "store_ready", return_value=True),
            patch.object(snapshots, "purge_all_snapshots_for_sources") as purge,
        ):
            completed = snapshots.drain_pending_source_snapshot_purges(db)

        self.assertEqual(completed, 1)
        purge.assert_not_called()
        self.assertEqual(db.execute.call_args_list[-1].args[1]["key"], "snapshot_purge:broken")
        self.assertEqual(db.execute.call_args_list[-1].args[1]["expected_value"], "not-json")
        db.commit.assert_called_once()

    def test_pending_source_purge_key_fits_schema_meta_key_column(self):
        key = snapshots._pending_source_purge_key("kb_article", "x" * 255)
        self.assertLessEqual(len(key), 80)
        self.assertTrue(key.startswith("snapshot_purge:"))

    def test_explicit_source_delete_queues_recovery_before_snapshot_drain(self):
        db = MagicMock()
        deleted = MagicMock()
        deleted.rowcount = 1
        db.execute.return_value = deleted
        source = [("ticket", "ticket-a")]
        with (
            patch.object(store_v2, "store_ready", return_value=True),
            patch.object(
                store_v2,
                "_commit_source_change_with_snapshot_purge_queue",
                return_value=source,
            ) as queued,
            patch.object(store_v2, "_drain_source_snapshot_purge_queue") as drained,
        ):
            self.assertEqual(store_v2.delete_source_chunks(db, "ticket", "ticket-a"), 1)

        queued.assert_called_once_with(db, source)
        drained.assert_called_once_with(db, source)

    def test_snapshot_insert_failure_rolls_back_evidence_and_references_together(self):
        db = MagicMock()
        db.execute.side_effect = [MagicMock(), RuntimeError("reference insert failed")]
        result = [{
            "chunk_id": "chunk-a",
            "content_hash": "content-a",
            "parent_hash": "parent-a",
            "source_type": "ticket",
            "source_id": "ticket-a",
        }]

        with (
            patch.object(snapshots, "store_ready", return_value=True),
            patch.object(snapshots, "_manifest_is_current", return_value=True),
            patch.object(snapshots, "corpus_generation", return_value=1),
            patch.object(snapshots, "_prune_expired_rag_data"),
        ):
            with self.assertRaisesRegex(RuntimeError, "reference insert failed"):
                snapshots.create_snapshot(
                    db,
                    actor_id="agent-a",
                    actor_role="agent",
                    include_private_comments=False,
                    allowed_assignee_id="agent-a",
                    query="printer",
                    embedding_identity="model-v1",
                    packed_evidence=[{"text": "evidence"}],
                    citation_allowlist={},
                    retrieval_results=result,
                )

        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_query_cache_write_uses_bounded_shared_retention_maintenance(self):
        db = MagicMock()
        db.bind.dialect.name = "postgresql"
        db.execute.return_value.rowcount = 0
        with (
            patch.object(retrieval_v2, "SessionLocal", return_value=db),
            patch.object(retrieval_v2, "store_ready", return_value=True),
            patch.object(retrieval_v2, "dimensions", return_value=3),
            patch("app.backend.rag.snapshots._prune_expired_rag_data") as prune,
        ):
            retrieval_v2._cache_put("tenant-a", "a" * 64, "model-v1", [0.1] * 3)

        prune.assert_called_once_with(db, retrieval_v2._CACHE_MAINTENANCE_BATCH)
        capacity_delete = db.execute.call_args_list[-1]
        self.assertEqual(
            capacity_delete.args[1]["limit"], retrieval_v2._CACHE_MAINTENANCE_BATCH
        )
        self.assertIn("LIMIT :limit", str(capacity_delete.args[0]))
        db.commit.assert_called_once()

    def test_expired_rag_prune_is_bounded_and_committed_together(self):
        db = MagicMock()
        snapshot_delete = MagicMock()
        snapshot_delete.rowcount = 3
        cache_delete = MagicMock()
        cache_delete.rowcount = 2
        db.execute.side_effect = [snapshot_delete, cache_delete]

        with patch.object(snapshots, "store_ready", return_value=True):
            result = snapshots.prune_expired_rag_data(db, max_rows=999_999)

        self.assertEqual(result, {"snapshots": 3, "query_cache": 2})
        self.assertEqual(db.execute.call_count, 2)
        for call in db.execute.call_args_list:
            self.assertEqual(call.args[1]["limit"], 5_000)
        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    def test_read_flag_requires_deployment_owned_scope_allowlist(self):
        with patch.dict(os.environ, {
            "TICKET_RAG_SCOPE_KEY": "tenant-a",
            "TICKET_RAG_V2_SCOPE_ALLOWLIST": "tenant-b",
            "TICKET_RAG_V2_READ_ENABLED": "true",
            "TICKET_RAG_V2_WRITE_ENABLED": "true",
        }, clear=False):
            self.assertFalse(config.read_enabled())
        with patch.dict(os.environ, {
            "TICKET_RAG_SCOPE_KEY": "tenant-a",
            "TICKET_RAG_V2_SCOPE_ALLOWLIST": "tenant-a",
            "TICKET_RAG_V2_READ_ENABLED": "true",
            "TICKET_RAG_V2_WRITE_ENABLED": "true",
        }, clear=False):
            self.assertTrue(config.read_enabled())

    def test_auth_fingerprint_changes_with_every_authorization_boundary(self):
        base = snapshots.auth_fingerprint(
            actor_id="agent-1",
            actor_role="agent",
            include_private_comments=False,
            allowed_assignee_id="agent-1",
            scope="tenant-a",
        )
        elevated = snapshots.auth_fingerprint(
            actor_id="agent-1",
            actor_role="supervisor",
            include_private_comments=True,
            allowed_assignee_id=None,
            scope="tenant-a",
        )
        other_scope = snapshots.auth_fingerprint(
            actor_id="agent-1",
            actor_role="agent",
            include_private_comments=False,
            allowed_assignee_id="agent-1",
            scope="tenant-b",
        )

        self.assertNotEqual(base, elevated)
        self.assertNotEqual(base, other_scope)

    def test_migration_rejects_existing_dimension_mismatch(self):
        migration = importlib.import_module(
            "migrations.versions.0008_rag_hybrid_chunks_v2"
        )
        bind = MagicMock()
        relation_result = MagicMock()
        relation_result.scalar.return_value = "ticket_search_documents"
        type_result = MagicMock()
        type_result.scalar.return_value = "vector(1536)"
        bind.execute.side_effect = [relation_result, type_result]

        with self.assertRaises(RuntimeError):
            migration._preflight_dimensions(bind, 3)


if __name__ == "__main__":
    unittest.main()
