import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend import main
from app.backend.database import (
    AIArtifactRecord,
    AIUsageEventRecord,
    Base,
)


class StartupRetentionCleanupTests(unittest.TestCase):
    def test_rag_retention_loop_runs_a_later_batch_without_new_requests(self):
        calls = []

        async def sleep_once(_seconds):
            raise asyncio.CancelledError()

        with (
            patch.object(main, "_prune_expired_rag_data_safely", side_effect=lambda: calls.append("pruned")),
            patch.object(main.asyncio, "sleep", new=sleep_once),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(main._rag_retention_cleanup_loop())

        self.assertEqual(calls, ["pruned"])

    def test_rag_retention_failure_isolated_from_background_loop(self):
        calls = []

        async def sleep_once(_seconds):
            calls.append("sleep")
            raise asyncio.CancelledError()

        with (
            patch.object(main, "_prune_expired_rag_data_safely", side_effect=RuntimeError("db")),
            patch.object(main.asyncio, "sleep", new=sleep_once),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(main._rag_retention_cleanup_loop())

        self.assertEqual(calls, ["sleep"])

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        database_path = Path(self.tempdir.name) / "retention.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.now = datetime.utcnow()

    def tearDown(self):
        self.engine.dispose()
        self.tempdir.cleanup()

    def _usage(self, db, age_days: int):
        row = AIUsageEventRecord(
            actor_id=f"user-{age_days}-{db.query(AIUsageEventRecord).count()}",
            task="retention-test",
            created_at=self.now - timedelta(days=age_days),
        )
        db.add(row)
        return row

    def _artifact(self, db, *, active: bool, age_days: int):
        db.add(AIArtifactRecord(
            ticket_id=f"ticket-{active}-{age_days}-{db.query(AIArtifactRecord).count()}",
            artifact="summary",
            input_hash="a" * 64,
            pipeline_version="v1",
            provider="test",
            model="test",
            synthetic=False,
            content_hash="b" * 64,
            active=active,
            created_at=self.now - timedelta(days=age_days),
        ))

    def test_cleanup_uses_ordered_multiple_batches_and_per_start_cap(self):
        db = self.Session()
        try:
            for age_days in range(50, 38, -1):
                self._usage(db, age_days)
            self._usage(db, 1)  # current metric data must survive.
            self._artifact(db, active=False, age_days=100)
            self._artifact(db, active=True, age_days=100)
            db.commit()

            with patch.dict(os.environ, {
                "AI_RETENTION_CLEANUP_BATCH_SIZE": "10",
                "AI_RETENTION_CLEANUP_MAX_ROWS_PER_START": "44",
            }, clear=False):
                counts = main._prune_ai_operational_data(db)

            self.assertEqual(counts["usage_events"], 11)
            self.assertEqual(counts["inactive_artifacts"], 1)
            remaining_old_usage = db.query(AIUsageEventRecord).filter(
                AIUsageEventRecord.created_at < self.now - timedelta(days=30)
            ).all()
            self.assertEqual(len(remaining_old_usage), 1)
            # The newest expired usage record is the one left after ordered
            # oldest-first batches, proving the cap did not use one bulk delete.
            self.assertEqual(remaining_old_usage[0].created_at.date(), (self.now - timedelta(days=39)).date())
            self.assertEqual(db.query(AIUsageEventRecord).count(), 2)
            self.assertEqual(db.query(AIArtifactRecord).filter(AIArtifactRecord.active.is_(False)).count(), 0)
            self.assertEqual(db.query(AIArtifactRecord).filter(AIArtifactRecord.active.is_(True)).count(), 1)
        finally:
            db.close()

    def test_cleanup_retains_current_and_active_records_after_later_batches(self):
        db = self.Session()
        try:
            self._usage(db, 40)
            self._usage(db, 1)
            self._artifact(db, active=False, age_days=100)
            self._artifact(db, active=True, age_days=100)
            self._artifact(db, active=False, age_days=1)
            db.commit()

            with patch.dict(os.environ, {
                "AI_RETENTION_CLEANUP_BATCH_SIZE": "10",
                "AI_RETENTION_CLEANUP_MAX_ROWS_PER_START": "20",
            }, clear=False):
                counts = main._prune_ai_operational_data(db)

            self.assertEqual(counts["usage_events"], 1)
            self.assertEqual(counts["inactive_artifacts"], 1)
            self.assertEqual(db.query(AIUsageEventRecord).count(), 1)
            self.assertEqual(db.query(AIArtifactRecord).filter(AIArtifactRecord.active.is_(True)).count(), 1)
            self.assertEqual(db.query(AIArtifactRecord).filter(AIArtifactRecord.active.is_(False)).count(), 1)
        finally:
            db.close()

    def test_cleanup_failure_rolls_back_and_does_not_abort_startup(self):
        cleanup_db = Mock()
        start_background_services = AsyncMock()
        previous_llm_mgr = main.llm_mgr
        previous_engine_llm = main.engine.llm
        try:
            with (
                patch.object(main, "init_db"),
                patch.object(main.settings_module, "load_settings_into_env"),
                patch.object(main.settings_module, "get_bool", return_value=False),
                patch.object(main, "SessionLocal", return_value=cleanup_db),
                patch.object(main, "_prune_ai_operational_data", side_effect=RuntimeError("database unavailable")),
                patch("app.backend.rag.snapshots.prune_expired_rag_data", return_value={"snapshots": 0, "query_cache": 0}) as prune_rag,
                patch("app.backend.rag.snapshots.purge_ineligible_snapshots", return_value=0) as purge_ineligible_rag,
                patch("app.backend.rag.store_v2.purge_ineligible_chunks", return_value=0) as purge_ineligible_chunks,
                patch("app.backend.rag.snapshots.drain_pending_source_snapshot_purges", return_value=0) as drain_pending_rag,
                patch.object(main.ticket_vectors, "purge_private_comment_documents", return_value=0),
                patch.object(main.ticket_vectors, "purge_portal_ticket_documents", return_value=0),
                patch.object(main.ticket_vectors, "purge_unapproved_kb_documents", return_value=0),
                patch.object(main, "LLMManager"),
                patch.object(main, "_start_runtime_background_services", start_background_services),
            ):
                asyncio.run(main.startup())
        finally:
            # ``startup`` deliberately replaces these application globals.
            # The mocked manager must not leak into later API tests.
            main.llm_mgr = previous_llm_mgr
            main.engine.llm = previous_engine_llm

        cleanup_db.rollback.assert_called_once()
        cleanup_db.close.assert_called_once()
        prune_rag.assert_called_once_with(cleanup_db)
        purge_ineligible_rag.assert_called_once_with(cleanup_db)
        purge_ineligible_chunks.assert_called_once_with(cleanup_db)
        drain_pending_rag.assert_called_once_with(cleanup_db)
        start_background_services.assert_awaited_once()
