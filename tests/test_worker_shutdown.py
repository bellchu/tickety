"""Regression guards for bounded worker termination and durable recovery."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.backend import sync_worker, worker
from app.backend.rag import embedding_worker


class WorkerShutdownTests(unittest.TestCase):
    def setUp(self):
        sync_worker._scheduler = None
        sync_worker._admission_stopped.clear()
        sync_worker._admission_generation = 0
        embedding_worker._worker_thread = None
        embedding_worker._stop_event.clear()

    def tearDown(self):
        sync_worker._scheduler = None
        sync_worker._admission_stopped.clear()
        sync_worker._admission_generation = 0
        embedding_worker._worker_thread = None
        embedding_worker._stop_event.clear()

    def test_scheduler_shutdown_does_not_wait_behind_a_blocked_job(self):
        scheduler = MagicMock()
        entered = threading.Event()
        release = threading.Event()

        def shutdown(*, wait):
            entered.set()
            if wait:
                release.wait()

        scheduler.shutdown.side_effect = shutdown
        sync_worker._scheduler = scheduler

        started = time.monotonic()
        self.assertTrue(sync_worker.stop_sync_worker(wait=False))
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertTrue(entered.is_set())
        self.assertTrue(sync_worker._admission_stopped.is_set())
        scheduler.shutdown.assert_called_once_with(wait=False)
        release.set()

    def test_nonblocking_restart_cannot_reopen_an_old_scheduler_callback(self):
        old_scheduler = MagicMock()
        replacement = MagicMock()
        sync_worker._scheduler = old_scheduler
        sync_worker._admission_generation = 41
        self.assertTrue(sync_worker.stop_sync_worker(wait=False))

        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "TICKETY_PROCESS_ROLE": "worker",
            }, clear=True),
            patch.object(sync_worker, "BackgroundScheduler", return_value=replacement),
        ):
            self.assertTrue(sync_worker.start_sync_worker())

        admitted = []
        sync_worker._run_scheduled_job(lambda: admitted.append("old"), 41)
        self.assertEqual(admitted, [])
        self.assertTrue(sync_worker.stop_sync_worker(wait=False))

    def test_sigterm_during_scheduler_start_prevents_rag_start(self):
        handlers = {}
        stopped = threading.Event()
        cleanup_db = MagicMock()
        seen_admission = []

        def register(signum, handler):
            handlers[signum] = handler

        def race_scheduler_start(*, admission_allowed, on_job_completion=None):
            handlers[worker.signal.SIGTERM](worker.signal.SIGTERM, None)
            seen_admission.append(admission_allowed())
            return False

        with (
            patch.object(worker, "init_db"),
            patch.object(worker.settings_module, "load_settings_into_env"),
            patch.object(worker, "SessionLocal", return_value=cleanup_db),
            patch.object(worker.ticket_vectors, "purge_private_comment_documents"),
            patch.object(worker, "process_role", return_value="worker"),
            patch.object(worker.threading, "Event", return_value=stopped),
            patch.object(worker.signal, "signal", side_effect=register),
            patch.object(worker, "_arm_sigterm_shutdown_watchdog"),
            patch.object(worker, "start_sync_worker", side_effect=race_scheduler_start),
            patch.object(worker, "start_embedding_worker") as start_embedding,
        ):
            self.assertEqual(worker.run(), 0)

        self.assertEqual(seen_admission, [False])
        start_embedding.assert_not_called()

    def test_api_role_cannot_clear_a_live_worker_rag_health_contract(self):
        cleanup_db = MagicMock()
        with (
            patch.object(worker, "init_db"),
            patch.object(worker.settings_module, "load_settings_into_env"),
            patch.object(worker, "SessionLocal", return_value=cleanup_db),
            patch.object(worker.ticket_vectors, "purge_private_comment_documents"),
            patch.object(worker, "process_role", return_value="api"),
            patch.object(worker, "clear_worker_health_markers") as clear_markers,
        ):
            self.assertEqual(worker.run(), 2)

        clear_markers.assert_not_called()

    def test_scheduler_start_race_is_closed_before_it_is_published(self):
        scheduler = MagicMock()
        admission_allowed = MagicMock(side_effect=[True, False])
        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "TICKETY_PROCESS_ROLE": "worker",
            }, clear=True),
            patch.object(sync_worker, "BackgroundScheduler", return_value=scheduler),
        ):
            self.assertFalse(
                sync_worker.start_sync_worker(admission_allowed=admission_allowed)
            )

        self.assertIsNone(sync_worker._scheduler)
        scheduler.start.assert_called_once_with()
        scheduler.shutdown.assert_called_once_with(wait=False)
        self.assertTrue(sync_worker._admission_stopped.is_set())

    def test_embedding_shutdown_deadline_returns_while_job_is_blocked(self):
        release = threading.Event()
        thread = threading.Thread(target=release.wait, daemon=True)
        thread.start()
        embedding_worker._worker_thread = thread

        started = time.monotonic()
        self.assertFalse(
            embedding_worker.stop_embedding_worker(wait=True, timeout_seconds=0.01)
        )
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertTrue(embedding_worker._stop_event.is_set())
        # Keep the live reference: a still-running thread must never be
        # replaced in-process and duplicate its durable leases.
        self.assertIs(embedding_worker._worker_thread, thread)

        release.set()
        thread.join(timeout=1)
        self.assertTrue(embedding_worker.stop_embedding_worker(wait=False))

    def test_entrypoint_closes_admission_before_bounded_embedding_wait(self):
        stopped = MagicMock()
        stopped.wait.return_value = None
        stopped.is_set.return_value = False
        cleanup_db = MagicMock()
        calls = []

        def stop_embedding(*, wait, timeout_seconds=None):
            calls.append(("embedding", wait, timeout_seconds))
            return wait

        def stop_scheduler(*, wait):
            calls.append(("scheduler", wait, None))
            return True

        with (
            patch.dict(os.environ, {"WORKER_SHUTDOWN_DEADLINE_SECONDS": "20"}, clear=False),
            patch.object(worker, "init_db"),
            patch.object(worker.settings_module, "load_settings_into_env"),
            patch.object(worker, "SessionLocal", return_value=cleanup_db),
            patch.object(worker.ticket_vectors, "purge_private_comment_documents"),
            patch.object(worker, "process_role", return_value="worker"),
            patch.object(worker, "start_sync_worker", return_value=True),
            patch.object(
                worker, "start_embedding_worker", return_value=True
            ) as start_embedding,
            patch.object(worker.threading, "Event", return_value=stopped),
            patch.object(worker, "stop_embedding_worker", side_effect=stop_embedding),
            patch.object(worker, "stop_sync_worker", side_effect=stop_scheduler),
            patch.object(worker, "_arm_heartbeat_watchdog") as arm_heartbeat_watchdog,
            patch.object(worker, "clear_worker_health_markers"),
            patch.object(worker, "write_rag_embedding_health_requirement") as write_requirement,
            patch.object(worker, "write_rag_embedding_heartbeat") as write_rag_heartbeat,
            patch.object(
                worker,
                "configured_rag_embedding_heartbeat_max_age_seconds",
                return_value=125,
            ),
        ):
            self.assertEqual(worker.run(), 0)

        self.assertEqual(calls[0], ("embedding", False, None))
        self.assertEqual(calls[1], ("scheduler", False, None))
        self.assertEqual(calls[2][0:2], ("embedding", True))
        self.assertGreater(calls[2][2], 0)
        self.assertLessEqual(calls[2][2], 20)
        self.assertIs(
            start_embedding.call_args.kwargs["on_progress"],
            write_rag_heartbeat,
        )
        arm_heartbeat_watchdog.assert_called_once_with(
            stopped, embedding_worker_required=True
        )
        write_requirement.assert_called_once_with(125)
        write_rag_heartbeat.assert_called_once_with()

    def test_deadline_is_bounded_even_for_invalid_environment_values(self):
        with patch.dict(os.environ, {"WORKER_SHUTDOWN_DEADLINE_SECONDS": "999"}, clear=False):
            self.assertEqual(worker.shutdown_deadline_seconds(), 30)
        with patch.dict(os.environ, {"WORKER_SHUTDOWN_DEADLINE_SECONDS": "invalid"}, clear=False):
            self.assertEqual(worker.shutdown_deadline_seconds(), 20)

    def test_rag_heartbeat_budget_covers_one_bounded_provider_call(self):
        with patch.dict(os.environ, {
            "WORKER_HEALTHCHECK_MAX_AGE_SECONDS": "120",
            "TICKET_RAG_WORKER_POLL_SECONDS": "2",
            "TICKET_EMBEDDING_TIMEOUT_SECONDS": "120",
        }, clear=False):
            self.assertEqual(
                worker.configured_rag_embedding_heartbeat_max_age_seconds(), 125
            )

    def test_worker_start_clears_inherited_markers_before_database_startup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            scheduler_marker = os.path.join(temporary_directory, "worker-heartbeat")
            rag_marker = os.path.join(temporary_directory, "rag-heartbeat")
            requirement_marker = os.path.join(temporary_directory, "rag-required")
            environment = {
                "WORKER_HEARTBEAT_PATH": scheduler_marker,
                "WORKER_RAG_HEARTBEAT_PATH": rag_marker,
                "WORKER_RAG_HEALTH_REQUIRED_PATH": requirement_marker,
            }
            with patch.dict(os.environ, environment, clear=False):
                worker.write_worker_heartbeat()
                worker.write_rag_embedding_heartbeat()
                worker.write_rag_embedding_health_requirement(125)
                self.assertTrue(worker.worker_healthcheck())

                def observe_database_startup():
                    self.assertFalse(worker.worker_healthcheck())
                    self.assertFalse(os.path.exists(scheduler_marker))
                    self.assertFalse(os.path.exists(rag_marker))
                    self.assertFalse(os.path.exists(requirement_marker))

                cleanup_db = MagicMock()
                with (
                    patch.object(worker, "init_db", side_effect=observe_database_startup),
                    patch.object(worker.settings_module, "load_settings_into_env"),
                    patch.object(worker, "SessionLocal", return_value=cleanup_db),
                    patch.object(worker.ticket_vectors, "purge_private_comment_documents"),
                    patch.object(worker, "process_role", return_value="worker"),
                    patch.object(worker, "start_sync_worker", return_value=False),
                    patch.object(worker.signal, "signal"),
                ):
                    self.assertEqual(worker.run(), 1)

    def test_healthcheck_requires_a_recent_completed_heartbeat(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker = os.path.join(temporary_directory, "worker-heartbeat")
            with patch.dict(os.environ, {
                "WORKER_HEARTBEAT_PATH": marker,
                "WORKER_HEALTHCHECK_MAX_AGE_SECONDS": "30",
            }, clear=False):
                self.assertFalse(worker.worker_healthcheck())
                worker.write_worker_heartbeat()
                self.assertTrue(worker.worker_healthcheck())
                with patch.object(worker.time, "time", return_value=10_000_000_000):
                    self.assertFalse(worker.worker_healthcheck())

    def test_healthcheck_uses_parent_rag_contract_not_unhydrated_probe_settings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            scheduler_marker = os.path.join(temporary_directory, "worker-heartbeat")
            rag_marker = os.path.join(temporary_directory, "rag-heartbeat")
            environment = {
                "WORKER_HEARTBEAT_PATH": scheduler_marker,
                "WORKER_RAG_HEARTBEAT_PATH": rag_marker,
                "WORKER_HEALTHCHECK_MAX_AGE_SECONDS": "30",
                # Probe subprocesses do not hydrate SettingsRecord overrides;
                # they must follow the live parent's marker contract instead.
                "TICKET_RAG_V2_WRITE_ENABLED": "false",
                "TICKET_RAG_V2_WORKER_ENABLED": "false",
                "TICKET_EMBEDDING_ENABLED": "false",
            }
            with patch.dict(os.environ, environment, clear=False):
                worker.write_worker_heartbeat()
                worker.write_rag_embedding_health_requirement(125)
                self.assertFalse(worker.worker_healthcheck())
                worker.write_rag_embedding_heartbeat()
                self.assertTrue(worker.worker_healthcheck())

    def test_healthcheck_fails_closed_for_a_corrupt_parent_rag_contract(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            scheduler_marker = os.path.join(temporary_directory, "worker-heartbeat")
            rag_required = os.path.join(temporary_directory, "rag-required")
            with patch.dict(os.environ, {
                "WORKER_HEARTBEAT_PATH": scheduler_marker,
                "WORKER_RAG_HEALTH_REQUIRED_PATH": rag_required,
            }, clear=False):
                worker.write_worker_heartbeat()
                with open(rag_required, "w", encoding="ascii") as marker:
                    marker.write("not-a-valid-max-age\n")
                self.assertFalse(worker.worker_healthcheck())

    def test_heartbeat_watchdog_exits_when_rag_thread_stops_before_marker_expires(self):
        stopped = threading.Event()

        with (
            patch.object(worker, "embedding_worker_running", return_value=False),
            patch.object(worker, "worker_healthcheck", return_value=True),
            patch.object(worker.os, "_exit", side_effect=SystemExit(1)) as exit_process,
        ):
            with self.assertRaises(SystemExit) as raised:
                worker._exit_after_heartbeat_stall(
                    stopped,
                    embedding_worker_required=True,
                    poll_interval_seconds=0,
                )

        self.assertEqual(raised.exception.code, 1)
        exit_process.assert_called_once_with(1)

    def test_heartbeat_watchdog_exits_a_stalled_worker_for_compose_recovery(self):
        stopped = threading.Event()

        with patch.object(worker, "worker_healthcheck", return_value=False):
            with patch.object(worker.os, "_exit", side_effect=SystemExit(1)) as exit_process:
                with self.assertRaises(SystemExit) as raised:
                    worker._exit_after_heartbeat_stall(stopped, poll_interval_seconds=0)

        self.assertEqual(raised.exception.code, 1)
        exit_process.assert_called_once_with(1)

    def test_heartbeat_watchdog_stops_without_exiting_during_normal_shutdown(self):
        stopped = threading.Event()
        stopped.set()

        with patch.object(worker.os, "_exit") as exit_process:
            worker._exit_after_heartbeat_stall(stopped, poll_interval_seconds=0)

        exit_process.assert_not_called()

    def test_sigterm_arms_hard_exit_watchdog_without_affecting_normal_stop(self):
        handlers = {}
        stopped = MagicMock()
        stopped.is_set.return_value = False
        cleanup_db = MagicMock()

        def register(signum, handler):
            handlers[signum] = handler

        def wait_then_signal():
            handlers[worker.signal.SIGTERM](worker.signal.SIGTERM, None)

        stopped.wait.side_effect = wait_then_signal
        with (
            patch.dict(os.environ, {"WORKER_SHUTDOWN_DEADLINE_SECONDS": "20"}, clear=False),
            patch.object(worker, "init_db"),
            patch.object(worker.settings_module, "load_settings_into_env"),
            patch.object(worker, "SessionLocal", return_value=cleanup_db),
            patch.object(worker.ticket_vectors, "purge_private_comment_documents"),
            patch.object(worker, "process_role", return_value="worker"),
            patch.object(worker, "start_sync_worker", return_value=True),
            patch.object(worker, "start_embedding_worker", return_value=False),
            patch.object(worker.threading, "Event", return_value=stopped),
            patch.object(worker.signal, "signal", side_effect=register),
            patch.object(worker, "_arm_sigterm_shutdown_watchdog") as arm,
            patch.object(worker, "_arm_heartbeat_watchdog"),
            patch.object(worker, "stop_embedding_worker", return_value=True),
            patch.object(worker, "stop_sync_worker", return_value=True),
        ):
            self.assertEqual(worker.run(), 0)

        arm.assert_called_once_with(20)

    def test_watchdog_hard_exits_only_after_the_budget(self):
        with (
            patch.object(worker.time, "sleep") as sleep,
            patch.object(worker.os, "_exit") as hard_exit,
        ):
            worker._force_exit_after_shutdown_deadline(7)

        sleep.assert_called_once_with(7)
        hard_exit.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
