import importlib
import os
import unittest
from unittest.mock import MagicMock, patch

from app.backend.rag import chunking, config, embedding_worker, retrieval_v2, snapshots


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


class RagV2ConfigurationAndSnapshotTests(unittest.TestCase):
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
