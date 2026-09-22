import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.backend import main, ticket_vectors


class TicketVectorBackgroundRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await ticket_vectors.stop_background_ticket_refreshes()

    async def asyncTearDown(self):
        await ticket_vectors.stop_background_ticket_refreshes()

    async def test_failure_is_consumed_and_task_is_removed(self):
        with (
            patch.object(
                ticket_vectors,
                "_refresh_ticket_by_id",
                new=AsyncMock(side_effect=ValueError("invalid derived document")),
            ),
            patch("builtins.print") as report,
        ):
            self.assertTrue(
                ticket_vectors._schedule_background_ticket_refresh("ticket-failed", False)
            )
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        self.assertNotIn("ticket-failed", ticket_vectors._BACKGROUND_REFRESH_TASKS)
        self.assertTrue(
            any(
                "background_ticket_refresh_error" in str(call.args[0])
                for call in report.call_args_list
            )
        )

    async def test_transient_failure_retries_once(self):
        refresh = AsyncMock(side_effect=[ConnectionError("temporary"), 3])
        with (
            patch.dict(
                os.environ,
                {"TICKET_VECTOR_BACKGROUND_REFRESH_RETRY_DELAY_SECONDS": "0"},
            ),
            patch.object(ticket_vectors, "_refresh_ticket_by_id", new=refresh),
        ):
            self.assertTrue(
                ticket_vectors._schedule_background_ticket_refresh("ticket-retry", False)
            )
            task = ticket_vectors._BACKGROUND_REFRESH_TASKS["ticket-retry"]
            self.assertEqual(await task, 3)

        self.assertEqual(refresh.await_count, 2)

    async def test_duplicate_work_is_coalesced_and_shutdown_cancels_and_drains(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_refresh(_ticket_id, force=False):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with patch.object(ticket_vectors, "_refresh_ticket_by_id", new=blocked_refresh):
            self.assertTrue(
                ticket_vectors._schedule_background_ticket_refresh("ticket-active", False)
            )
            await started.wait()
            self.assertTrue(ticket_vectors._schedule_background_ticket_refresh("ticket-active", True))
            self.assertEqual(list(ticket_vectors._BACKGROUND_REFRESH_TASKS), ["ticket-active"])
            active = ticket_vectors._BACKGROUND_REFRESH_TASKS["ticket-active"]
            await ticket_vectors.stop_background_ticket_refreshes()

        self.assertTrue(cancelled.is_set())
        self.assertTrue(active.done())
        self.assertTrue(active.cancelled())
        self.assertFalse(ticket_vectors._BACKGROUND_REFRESH_TASKS)

    async def test_app_shutdown_stops_scheduler_before_draining_vector_work(self):
        calls = []
        previous_task = main._notification_dispatch_task
        previous_expected = main._notification_dispatch_expected
        main._notification_dispatch_task = None
        main._notification_dispatch_expected = False

        def stop_worker(*, wait=True):
            calls.append(("scheduler", wait))

        async def drain_vectors():
            calls.append("vectors")

        try:
            with (
                patch.object(main, "stop_sync_worker", side_effect=stop_worker),
                patch.object(
                    main.ticket_vectors,
                    "stop_background_ticket_refreshes",
                    new=AsyncMock(side_effect=drain_vectors),
                ),
            ):
                await main.shutdown()
        finally:
            main._notification_dispatch_task = previous_task
            main._notification_dispatch_expected = previous_expected

        self.assertEqual(calls, [("scheduler", False), "vectors"])
