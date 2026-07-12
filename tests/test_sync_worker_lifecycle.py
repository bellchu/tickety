import os
import unittest
from unittest.mock import MagicMock, patch

from app.backend import sync_worker


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
            self.assertEqual(first_scheduler.add_job.call_count, 2)

            sync_job = first_scheduler.add_job.call_args_list[0]
            self.assertEqual(sync_job.kwargs["seconds"], 10)
            self.assertEqual(sync_job.kwargs["max_instances"], 1)
            self.assertTrue(sync_job.kwargs["coalesce"])
            triage_job = first_scheduler.add_job.call_args_list[1]
            self.assertEqual(triage_job.kwargs["seconds"], 86_400)

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

    def test_invalid_scheduler_flag_fails_closed(self):
        with patch.dict(os.environ, {
            "APP_MODE": "production",
            "TICKETY_PROCESS_ROLE": "worker",
            "TICKETY_SCHEDULER_ENABLED": "flase",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                sync_worker.scheduler_enabled_for_process()


if __name__ == "__main__":
    unittest.main()
