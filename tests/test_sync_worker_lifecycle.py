import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import sync_worker
from app.backend.database import Base, SyncStateRecord


class SyncWorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        sync_worker._scheduler = None

    def tearDown(self):
        sync_worker._scheduler = None

    def test_production_defaults_to_api_only_scheduler_role(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "production"}, clear=True),
            patch.object(sync_worker, "BackgroundScheduler") as scheduler_class,
        ):
            self.assertEqual(sync_worker.process_role(), "api")
            self.assertFalse(sync_worker.scheduler_enabled_for_process())
            self.assertFalse(sync_worker.start_sync_worker())

        scheduler_class.assert_not_called()

    def test_api_role_cannot_be_overridden_by_enable_flag(self):
        with patch.dict(os.environ, {
            "APP_MODE": "production",
            "TICKETY_PROCESS_ROLE": "api",
            "TICKETY_SCHEDULER_ENABLED": "true",
        }, clear=True):
            self.assertFalse(sync_worker.scheduler_enabled_for_process())

    def test_demo_defaults_to_combined_process_role(self):
        with patch.dict(os.environ, {"APP_MODE": "demo"}, clear=True):
            self.assertEqual(sync_worker.process_role(), "all")
            self.assertTrue(sync_worker.scheduler_enabled_for_process())

    def test_scheduler_has_single_start_stop_and_restart_lifecycle(self):
        first_scheduler = MagicMock()
        second_scheduler = MagicMock()
        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "TICKETY_PROCESS_ROLE": "worker",
                "SYNC_INTERVAL_SECONDS": "1",
                "AUTO_TRIAGE_INTERVAL_SECONDS": "999999",
            }, clear=True),
            patch.object(
                sync_worker,
                "BackgroundScheduler",
                side_effect=[first_scheduler, second_scheduler],
            ) as scheduler_class,
        ):
            self.assertTrue(sync_worker.start_sync_worker())
            self.assertFalse(sync_worker.start_sync_worker())
            scheduler_class.assert_called_once_with(daemon=True)
            first_scheduler.start.assert_called_once_with()
            self.assertEqual(first_scheduler.add_job.call_count, 3)

            sync_job = first_scheduler.add_job.call_args_list[0]
            self.assertEqual(sync_job.kwargs["seconds"], 10)
            self.assertEqual(sync_job.kwargs["max_instances"], 1)
            self.assertTrue(sync_job.kwargs["coalesce"])
            triage_job = first_scheduler.add_job.call_args_list[1]
            self.assertEqual(triage_job.kwargs["seconds"], 86_400)
            risk_job = first_scheduler.add_job.call_args_list[2]
            self.assertIs(risk_job.args[0], sync_worker._risk_backfill_job)
            self.assertEqual(risk_job.kwargs["id"], "risk_backfill_job")
            self.assertEqual(risk_job.kwargs["seconds"], 60)
            self.assertEqual(risk_job.kwargs["max_instances"], 1)
            self.assertTrue(risk_job.kwargs["coalesce"])

            self.assertTrue(sync_worker.stop_sync_worker(wait=True))
            self.assertFalse(sync_worker.stop_sync_worker(wait=True))
            first_scheduler.shutdown.assert_called_once_with(wait=True)

            self.assertTrue(sync_worker.start_sync_worker())
            self.assertEqual(scheduler_class.call_count, 2)
            second_scheduler.start.assert_called_once_with()
            self.assertTrue(sync_worker.stop_sync_worker(wait=False))
            second_scheduler.shutdown.assert_called_once_with(wait=False)

    def test_scheduler_kill_switch_disables_worker_role(self):
        with patch.dict(os.environ, {
            "APP_MODE": "production",
            "TICKETY_PROCESS_ROLE": "worker",
            "TICKETY_SCHEDULER_ENABLED": "false",
        }, clear=True):
            self.assertFalse(sync_worker.scheduler_enabled_for_process())

    def test_directory_sync_is_a_separate_bounded_single_instance_job(self):
        scheduler = MagicMock()
        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "TICKETY_PROCESS_ROLE": "worker",
                "DIRECTORY_SYNC_ENABLED": "true",
                "DIRECTORY_SYNC_INTERVAL_SECONDS": "1",
            }, clear=True),
            patch.object(sync_worker, "BackgroundScheduler", return_value=scheduler),
        ):
            self.assertTrue(sync_worker.start_sync_worker())
            self.assertEqual(scheduler.add_job.call_count, 4)
            directory_job = scheduler.add_job.call_args_list[3]
            self.assertIs(directory_job.args[0], sync_worker._directory_sync_job)
            self.assertEqual(directory_job.kwargs["id"], "directory_sync_job")
            self.assertEqual(directory_job.kwargs["seconds"], 900)
            self.assertEqual(directory_job.kwargs["max_instances"], 1)
            self.assertTrue(directory_job.kwargs["coalesce"])
            self.assertTrue(sync_worker.stop_sync_worker(wait=False))

    def test_invalid_scheduler_flag_fails_closed(self):
        with patch.dict(os.environ, {
            "APP_MODE": "production",
            "TICKETY_PROCESS_ROLE": "worker",
            "TICKETY_SCHEDULER_ENABLED": "flase",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                sync_worker.scheduler_enabled_for_process()

    def test_status_withholds_stale_history_completion_during_timestamp_repair(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        try:
            with session_factory() as db:
                db.add(SyncStateRecord(
                    binding_id="legacy",
                    provider="freshservice",
                    recent_completed_at=datetime.utcnow(),
                    provider_timestamp_repair_version=0,
                    provider_timestamp_repair_processed=178,
                    background_history_scan_version=0,
                    background_history_page=17,
                    background_history_complete=True,
                    background_history_processed=1_700,
                    background_history_started_at=datetime.utcnow(),
                    background_history_through_at=datetime.utcnow(),
                ))
                db.commit()

            with (
                patch.object(sync_worker, "SessionLocal", session_factory),
                patch.object(sync_worker, "configured_provider", return_value="freshservice"),
                patch.object(sync_worker, "get_active_binding", return_value=None),
                patch.object(sync_worker, "expire_due_bindings"),
                patch.object(
                    sync_worker,
                    "attachment_storage_configured",
                    return_value=False,
                ),
            ):
                status = sync_worker.get_sync_status()

            self.assertTrue(status["provider_timestamp_repair_pending"])
            self.assertEqual(
                status["provider_timestamp_repair_days"],
                sync_worker.PROVIDER_TIMESTAMP_REPAIR_DAYS,
            )
            self.assertEqual(status["provider_timestamp_repair_processed"], 178)
            self.assertFalse(status["background_history_complete"])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
