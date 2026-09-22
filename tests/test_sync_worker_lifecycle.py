import base64
import json
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import settings, sync_worker
from app.backend.database import Base, SettingsRecord, SyncStateRecord


class SyncWorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        sync_worker._scheduler = None
        sync_worker._admission_stopped.clear()
        sync_worker._admission_generation = 0

    def tearDown(self):
        sync_worker._scheduler = None
        sync_worker._admission_stopped.clear()
        sync_worker._admission_generation = 0

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
            self.assertEqual(first_scheduler.add_job.call_count, 4)

            sync_job = first_scheduler.add_job.call_args_list[0]
            self.assertEqual(sync_job.kwargs["seconds"], 10)
            self.assertEqual(sync_job.kwargs["max_instances"], 1)
            self.assertTrue(sync_job.kwargs["coalesce"])
            triage_job = first_scheduler.add_job.call_args_list[2]
            self.assertEqual(triage_job.kwargs["seconds"], 86_400)
            risk_job = first_scheduler.add_job.call_args_list[3]
            self.assertIs(risk_job.args[0], sync_worker._run_scheduled_job)
            self.assertIs(risk_job.kwargs["args"][0], sync_worker._risk_backfill_job)
            self.assertEqual(risk_job.kwargs["id"], "risk_backfill_job")
            self.assertEqual(risk_job.kwargs["seconds"], 60)
            self.assertEqual(risk_job.kwargs["max_instances"], 1)
            self.assertTrue(risk_job.kwargs["coalesce"])
            cleanup_job = first_scheduler.add_job.call_args_list[1]
            self.assertIs(cleanup_job.kwargs["args"][0], sync_worker._attachment_blob_cleanup_job)
            self.assertEqual(cleanup_job.kwargs["id"], "attachment_blob_cleanup_job")
            self.assertEqual(cleanup_job.kwargs["seconds"], 300)
            self.assertEqual(cleanup_job.kwargs["max_instances"], 1)
            self.assertTrue(cleanup_job.kwargs["coalesce"])

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

    def test_completion_hook_installs_fixed_cadence_scheduler_heartbeat(self):
        scheduler = MagicMock()
        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "TICKETY_PROCESS_ROLE": "worker",
                # Valid low-frequency business schedules must not make a
                # healthy worker fail its 10-minute liveness bound.
                "SYNC_INTERVAL_SECONDS": "86400",
                "AUTO_TRIAGE_INTERVAL_SECONDS": "86400",
                "AI_RISK_BACKFILL_INTERVAL_SECONDS": "86400",
            }, clear=True),
            patch.object(sync_worker, "BackgroundScheduler", return_value=scheduler),
        ):
            self.assertTrue(sync_worker.start_sync_worker(on_job_completion=lambda: None))

        heartbeat = next(
            call for call in scheduler.add_job.call_args_list
            if call.kwargs["id"] == "heartbeat_job"
        )
        self.assertIs(heartbeat.kwargs["args"][0], sync_worker._heartbeat_job)
        self.assertEqual(heartbeat.kwargs["seconds"], 10)
        self.assertEqual(heartbeat.kwargs["misfire_grace_time"], 10)
        self.assertTrue(sync_worker.stop_sync_worker(wait=False))

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
            self.assertEqual(scheduler.add_job.call_count, 5)
            directory_job = scheduler.add_job.call_args_list[4]
            self.assertIs(directory_job.args[0], sync_worker._run_scheduled_job)
            self.assertIs(directory_job.kwargs["args"][0], sync_worker._directory_sync_job)
            self.assertEqual(directory_job.kwargs["id"], "directory_sync_job")
            self.assertEqual(directory_job.kwargs["seconds"], 900)
            self.assertEqual(directory_job.kwargs["max_instances"], 1)
            self.assertTrue(directory_job.kwargs["coalesce"])
            self.assertTrue(sync_worker.stop_sync_worker(wait=False))

    def test_attachment_cleanup_job_runs_without_provider_binding(self):
        with (
            patch.object(sync_worker, "_refresh_admin_settings"),
            patch.object(
                sync_worker,
                "collect_superseded_attachment_blobs",
                return_value={"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0},
            ) as collect,
        ):
            sync_worker._attachment_blob_cleanup_job()

        collect.assert_called_once_with()

    def test_sensitive_refresh_failures_block_all_external_scheduled_jobs(self):
        """A stale credential must not survive an unauthenticated DB update."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        keyring = {
            "TICKETY_SETTINGS_ENCRYPTION_ACTIVE_KID": "current",
            "TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON": json.dumps({
                "current": base64.b64encode(bytes(range(32))).decode("ascii"),
            }),
        }
        try:
            for corrupt_value in (
                "enc:v1:retired:AA==",
                "legacy-plaintext-sensitive-setting",
            ):
                with self.subTest(corrupt_value=corrupt_value):
                    with (
                        patch.object(settings, "SessionLocal", session_factory),
                        patch.dict(os.environ, keyring, clear=False),
                    ):
                        # Each corruption variant needs an independent
                        # pre-corruption store. The durable encryption fence
                        # now correctly rejects the first variant's malformed
                        # row before a later subtest could overwrite it.
                        with session_factory.begin() as db:
                            db.query(SettingsRecord).delete()
                        settings._write_db_overrides({
                            "FRESHSERVICE_API_KEY": "known-good-before-corruption",
                        })
                        with session_factory() as db:
                            persisted = db.get(SettingsRecord, "FRESHSERVICE_API_KEY")
                            self.assertTrue(persisted.value.startswith("enc:v1:current:"))

                        # Establish the old in-memory credential, then simulate a
                        # post-load database corruption or a pre-migration row.
                        settings.load_settings_into_env()
                        with session_factory.begin() as db:
                            db.get(SettingsRecord, "FRESHSERVICE_API_KEY").value = corrupt_value

                        with (
                            patch.object(sync_worker, "get_adapter") as get_adapter,
                            patch.object(sync_worker, "sync_tickets_from_external") as sync,
                            patch.object(
                                sync_worker,
                                "collect_superseded_attachment_blobs",
                            ) as collect,
                            patch.object(
                                sync_worker.directory_service,
                                "run_directory_sync",
                            ) as directory_sync,
                            patch.object(sync_worker, "_process_ai_candidates") as ai_process,
                        ):
                            sync_worker._sync_job()
                            sync_worker._attachment_blob_cleanup_job()
                            sync_worker._directory_sync_job()
                            sync_worker._auto_triage_job()

                        get_adapter.assert_not_called()
                        sync.assert_not_called()
                        collect.assert_not_called()
                        directory_sync.assert_not_called()
                        ai_process.assert_not_called()
        finally:
            engine.dispose()

    def test_transient_settings_refresh_error_keeps_the_next_sweep_eligible(self):
        with patch.object(
            sync_worker.settings_module,
            "refresh_settings_from_db",
            side_effect=RuntimeError("temporary database outage"),
        ):
            self.assertTrue(sync_worker._refresh_admin_settings())

    def test_invalid_scheduler_flag_fails_closed(self):
        with patch.dict(os.environ, {
            "APP_MODE": "production",
            "TICKETY_PROCESS_ROLE": "worker",
            "TICKETY_SCHEDULER_ENABLED": "flase",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                sync_worker.scheduler_enabled_for_process()

    def test_completed_callback_reports_heartbeat_but_stopped_callback_does_not(self):
        completed = []
        sync_worker._run_scheduled_job(
            lambda: None,
            0,
            on_completion=lambda: completed.append("healthy"),
        )
        self.assertEqual(completed, ["healthy"])

        sync_worker._admission_stopped.set()
        sync_worker._run_scheduled_job(
            lambda: None,
            0,
            on_completion=lambda: completed.append("stale"),
        )
        self.assertEqual(completed, ["healthy"])

    def test_stale_scheduler_generation_cannot_refresh_worker_heartbeat(self):
        completed = []
        sync_worker._admission_generation = 7
        sync_worker._run_scheduled_job(
            lambda: self.fail("a replaced scheduler must not run work"),
            6,
            on_completion=lambda: completed.append("stale"),
        )
        self.assertEqual(completed, [])

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
