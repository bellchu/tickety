"""Durable notification outbox behavior across independent API processes."""
import asyncio
from datetime import datetime, timedelta
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Response

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.backend import database, main
from app.backend.database import (
    Base, NotificationOutboxRecord, NotificationOutboxSequenceRecord,
    TicketRecord, UserRecord,
)
from app.backend.schema import PointsAwardedNotification


class NotificationOutboxTests(unittest.TestCase):
    def setUp(self):
        self.previous_dispatch_state = (
            main._notification_dispatch_task,
            main._notification_dispatch_expected,
            main._notification_dispatch_last_success_at,
            main._notification_dispatch_last_error_at,
            main._notification_dispatch_consecutive_failures,
        )
        self.previous_notification_subscribers = list(main._notification_subscribers)
        self.previous_notification_activity = dict(main._notification_subscriber_activity)
        self.previous_notification_locks = dict(main._notification_subscriber_send_locks)
        main._notification_subscribers.clear()
        main._notification_subscriber_activity.clear()
        main._notification_subscriber_send_locks.clear()
        # These tests exercise durable ordering and cleanup with lightweight
        # socket doubles. Session revalidation is covered by the session
        # boundary suite using real SessionRecord rows.
        self.subscriber_authorization = patch.object(
            main, "_notification_subscriber_authorized", return_value=True
        )
        self.subscriber_authorization.start()
        main._notification_dispatch_task = None
        main._notification_dispatch_expected = False
        main._notification_dispatch_last_success_at = None
        main._notification_dispatch_last_error_at = None
        main._notification_dispatch_consecutive_failures = 0
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_url = f"sqlite:///{self.tempdir.name}/notification-outbox.db"
        self.engine_a = create_engine(
            self.database_url, connect_args={"check_same_thread": False}
        )
        self.engine_b = create_engine(
            self.database_url, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine_a)
        self.sessions_a = sessionmaker(bind=self.engine_a)
        self.sessions_b = sessionmaker(bind=self.engine_b)
        with self.sessions_a() as db:
            db.add(NotificationOutboxSequenceRecord(
                singleton_id=1, next_dispatch_order=0
            ))
            db.commit()

    def tearDown(self):
        (
            main._notification_dispatch_task,
            main._notification_dispatch_expected,
            main._notification_dispatch_last_success_at,
            main._notification_dispatch_last_error_at,
            main._notification_dispatch_consecutive_failures,
        ) = self.previous_dispatch_state
        main._notification_subscribers[:] = self.previous_notification_subscribers
        main._notification_subscriber_activity.clear()
        main._notification_subscriber_activity.update(self.previous_notification_activity)
        main._notification_subscriber_send_locks.clear()
        main._notification_subscriber_send_locks.update(self.previous_notification_locks)
        self.subscriber_authorization.stop()
        self.engine_b.dispose()
        self.engine_a.dispose()
        self.tempdir.cleanup()

    @staticmethod
    def _payload(event_id=1, user_id="recipient"):
        return PointsAwardedNotification(
            event_id=event_id,
            ticket_id="ticket-1",
            ticket_subject="Resolved ticket",
            user_id=user_id,
            user_name="Recipient",
            points_earned=15,
            new_total=15,
            new_tier=1,
            tier_promoted=False,
            new_momentum=1,
        )

    def _insert(
        self, *, event_id=1, row_id=None, payload=None, expires_at=None, key=None
    ):
        payload = payload or self._payload(event_id)
        with self.sessions_a() as db:
            db.add(NotificationOutboxRecord(
                id=row_id or event_id,
                dispatch_order=event_id,
                recipient_user_id=payload.user_id,
                event_type="points_awarded",
                payload_json=main._points_notification_payload(payload),
                dedupe_key=key or f"test:{event_id}",
                expires_at=expires_at or datetime.utcnow() + timedelta(hours=1),
            ))
            db.commit()

    def test_each_independent_dispatcher_delivers_the_shared_event_locally(self):
        first, second = AsyncMock(), AsyncMock()
        dispatcher_a = main._NotificationOutboxDispatcher(first)
        dispatcher_b = main._NotificationOutboxDispatcher(second)
        # Each represents a separate API process with its own Engine/pool,
        # sharing only the durable file-backed database.
        with patch.object(main, "SessionLocal", self.sessions_a):
            asyncio.run(dispatcher_a.initialize())
        with patch.object(main, "SessionLocal", self.sessions_b):
            asyncio.run(dispatcher_b.initialize())
        self._insert()

        with patch.object(main, "SessionLocal", self.sessions_a):
            asyncio.run(dispatcher_a.dispatch_once())
        with patch.object(main, "SessionLocal", self.sessions_b):
            asyncio.run(dispatcher_b.dispatch_once())

        first.assert_awaited_once()
        second.assert_awaited_once()
        self.assertEqual(first.await_args.args[0]["event_id"], 1)
        self.assertEqual(second.await_args.args[0]["user_id"], "recipient")

    def test_cursor_batches_and_skips_invalid_or_expired_payloads(self):
        sent = AsyncMock()
        dispatcher = main._NotificationOutboxDispatcher(sent)
        with patch.object(main, "SessionLocal", self.sessions_a):
            asyncio.run(dispatcher.initialize())
        self._insert(event_id=1)
        self._insert(event_id=2)
        with self.sessions_a() as db:
            invalid = db.get(NotificationOutboxRecord, 2)
            invalid.payload_json = '{"not":"a notification"}'
            db.add(NotificationOutboxRecord(
                id=3, dispatch_order=3,
                recipient_user_id="recipient", event_type="points_awarded",
                payload_json=main._points_notification_payload(self._payload(3)),
                dedupe_key="expired", expires_at=datetime.utcnow() - timedelta(seconds=1),
            ))
            db.commit()
        with patch.dict(os.environ, {"NOTIFICATION_OUTBOX_BATCH_SIZE": "1"}, clear=False):
            with patch.object(main, "SessionLocal", self.sessions_a):
                self.assertEqual(asyncio.run(dispatcher.dispatch_once()), 1)
                self.assertEqual(asyncio.run(dispatcher.dispatch_once()), 1)
        self.assertEqual(dispatcher.cursor, 2)
        sent.assert_awaited_once()

    def test_live_dispatch_rejects_mismatched_payload_cursor_without_suppressing_replay(self):
        """A corrupt live row must not move a browser past later valid orders."""
        sent = AsyncMock()
        dispatcher = main._NotificationOutboxDispatcher(sent)
        with (
            patch.object(main, "SessionLocal", self.sessions_a),
            patch.dict(os.environ, {"NOTIFICATION_OUTBOX_BATCH_SIZE": "1"}, clear=False),
        ):
            asyncio.run(dispatcher.initialize())
            self._insert(event_id=1, payload=self._payload(100))
            self._insert(event_id=2, payload=self._payload(2))
            self.assertEqual(asyncio.run(dispatcher.dispatch_once()), 1)
            # The first row is schema-valid but its claimed browser cursor
            # differs from its durable dispatch order, so it never reaches a
            # live socket.
            sent.assert_not_awaited()
            self.assertEqual(asyncio.run(dispatcher.dispatch_once()), 1)

        sent.assert_awaited_once_with(self._payload(2).model_dump(mode="json"))
        self.assertEqual(dispatcher.cursor, 2)

        # The durable rows remain available for reconnect recovery.  The bad
        # row advances only to its own verified order, then the next valid row
        # is still delivered rather than being skipped by its forged id 100.
        socket = MagicMock()
        socket.send_json = AsyncMock()
        with patch.object(main, "SessionLocal", self.sessions_a):
            self.assertEqual(asyncio.run(main._register_notification_subscriber_with_replay(
                "recipient", socket, 0
            )), (True, False))
        self.assertEqual(
            [call.args[0] for call in socket.send_json.await_args_list],
            [
                {"type": "notification_cursor_advance", "cursor": 1},
                self._payload(2).model_dump(mode="json"),
            ],
        )
        main._remove_notification_subscriber("recipient", socket)

    def test_award_and_outbox_are_one_transaction(self):
        with self.sessions_a() as db:
            db.add_all((
                UserRecord(id="award-user", name="Award User", role="agent", is_active=True),
                TicketRecord(
                    id="award-ticket", subject="Resolved", status="Resolved",
                    workflow_status="Resolved", priority="P3", assignee_id="award-user",
                ),
            ))
            db.commit()
            ticket = db.get(TicketRecord, "award-ticket")
            asyncio.run(main._check_resolution_and_award(ticket, db=db))
            self.assertTrue(db.get(TicketRecord, "award-ticket").points_awarded_sent)
            outbox = db.query(NotificationOutboxRecord).one()
            self.assertEqual(outbox.dedupe_key, "points_award:award-ticket")
            self.assertEqual(
                main._parse_points_notification(outbox.payload_json)["event_id"],
                outbox.dispatch_order,
            )

        # A duplicate outbox key makes the entire later award transaction roll
        # back; the points marker must never be committed without its event.
        with self.sessions_a() as db:
            db.add_all((
                UserRecord(id="rollback-user", name="Rollback", role="agent", is_active=True),
                TicketRecord(
                    id="rollback-ticket", subject="Resolved", status="Resolved",
                    workflow_status="Resolved", priority="P3", assignee_id="rollback-user",
                ),
                NotificationOutboxRecord(
                    dispatch_order=2, recipient_user_id="rollback-user", event_type="points_awarded",
                    payload_json="{}", dedupe_key="points_award:rollback-ticket",
                    expires_at=datetime.utcnow() + timedelta(hours=1),
                ),
            ))
            db.commit()
            with self.assertRaises(Exception):
                asyncio.run(main._check_resolution_and_award(db.get(TicketRecord, "rollback-ticket"), db=db))
            db.rollback()
            self.assertFalse(db.get(TicketRecord, "rollback-ticket").points_awarded_sent)

    def test_api_dispatcher_prunes_expired_rows_without_a_worker(self):
        self._insert(event_id=1, expires_at=datetime.utcnow() - timedelta(seconds=1))
        self._insert(event_id=2)
        dispatcher = main._NotificationOutboxDispatcher(AsyncMock())
        with patch.object(main, "SessionLocal", self.sessions_a):
            # Production API roles own this bounded cleanup; no worker process
            # needs to be present for outbox retention to make progress.
            asyncio.run(dispatcher.initialize())
            asyncio.run(dispatcher.dispatch_once())
        with self.sessions_a() as db:
            self.assertIsNone(db.get(NotificationOutboxRecord, 1))
            self.assertIsNotNone(db.get(NotificationOutboxRecord, 2))

    def test_pruning_runs_multiple_bounded_batches_without_deleting_live_rows(self):
        expired_at = datetime.utcnow() - timedelta(seconds=1)
        for event_id in range(1, 302):
            self._insert(event_id=event_id, expires_at=expired_at)
        self._insert(event_id=302)
        with (
            patch.object(main, "SessionLocal", self.sessions_a),
            patch.dict(os.environ, {
                "NOTIFICATION_OUTBOX_PRUNE_BATCH_SIZE": "100",
                "NOTIFICATION_OUTBOX_PRUNE_BATCHES_PER_RUN": "3",
            }, clear=False),
        ):
            self.assertEqual(main._prune_expired_notification_outbox(), 300)
        with self.sessions_a() as db:
            self.assertEqual(
                db.query(NotificationOutboxRecord).filter(
                    NotificationOutboxRecord.expires_at <= datetime.utcnow()
                ).count(),
                1,
            )
            self.assertIsNotNone(db.get(NotificationOutboxRecord, 302))

    def test_restart_after_commit_starts_at_highwater_without_historical_toast(self):
        self._insert()
        sent = AsyncMock()
        restarted = main._NotificationOutboxDispatcher(sent)
        with patch.object(main, "SessionLocal", self.sessions_b):
            asyncio.run(restarted.initialize())
            self.assertEqual(asyncio.run(restarted.dispatch_once()), 0)
        sent.assert_not_awaited()

    def test_reconnect_replays_only_current_users_unexpired_events_in_dispatch_order(self):
        self._insert(event_id=3, payload=self._payload(3, "recipient"))
        self._insert(event_id=4, payload=self._payload(4, "other-user"))
        self._insert(event_id=5, payload=self._payload(5, "recipient"), expires_at=datetime.utcnow() - timedelta(seconds=1))
        socket = MagicMock()
        socket.send_json = AsyncMock()
        with patch.object(main, "SessionLocal", self.sessions_a):
            self.assertEqual(asyncio.run(main._register_notification_subscriber_with_replay(
                "recipient", socket, 0
            )), (True, False))
        self.assertEqual(
            [call.args[0]["event_id"] for call in socket.send_json.await_args_list], [3]
        )
        self.assertIn(("recipient", socket), main._notification_subscribers)
        main._remove_notification_subscriber("recipient", socket)

    def test_reconnect_replay_is_bounded_without_advancing_past_its_window(self):
        for event_id in (1, 2, 3):
            self._insert(event_id=event_id)
        socket = MagicMock()
        socket.send_json = AsyncMock()
        socket.close = AsyncMock()
        with (
            patch.object(main, "SessionLocal", self.sessions_a),
            patch.dict(os.environ, {"NOTIFICATION_OUTBOX_REPLAY_BATCH_SIZE": "2"}, clear=False),
        ):
            self.assertEqual(asyncio.run(main._register_notification_subscriber_with_replay(
                "recipient", socket, 0
            )), (True, True))
        self.assertEqual(
            [call.args[0]["event_id"] for call in socket.send_json.await_args_list], [1, 2]
        )
        socket.close.assert_awaited_once_with(code=1013)
        self.assertNotIn(("recipient", socket), main._notification_subscribers)

        continued = MagicMock()
        continued.send_json = AsyncMock()
        continued.close = AsyncMock()
        with (
            patch.object(main, "SessionLocal", self.sessions_a),
            patch.dict(os.environ, {"NOTIFICATION_OUTBOX_REPLAY_BATCH_SIZE": "2"}, clear=False),
        ):
            self.assertEqual(asyncio.run(main._register_notification_subscriber_with_replay(
                "recipient", continued, 2
            )), (True, False))
        self.assertEqual(
            [call.args[0]["event_id"] for call in continued.send_json.await_args_list], [3]
        )
        main._remove_notification_subscriber("recipient", continued)

    def test_replay_advances_a_verified_cursor_past_rejected_rows_before_valid_event(self):
        """Malformed rows cannot make bounded reconnect replay loop forever."""
        with self.sessions_a() as db:
            for event_id, payload_json in (
                (1, '{"not":"a notification"}'),
                (2, '[]'),
                (3, '{"event_id":3,"user_id":"recipient"}'),
                # This is structurally valid but lies about its durable id.
                (4, main._points_notification_payload(self._payload(99))),
                (5, main._points_notification_payload(self._payload(5))),
            ):
                db.add(NotificationOutboxRecord(
                    id=event_id,
                    dispatch_order=event_id,
                    recipient_user_id="recipient",
                    event_type="points_awarded",
                    payload_json=payload_json,
                    dedupe_key=f"replay-rejected:{event_id}",
                    expires_at=datetime.utcnow() + timedelta(hours=1),
                ))
            db.commit()

        first = MagicMock()
        first.send_json = AsyncMock()
        first.close = AsyncMock()
        with (
            patch.object(main, "SessionLocal", self.sessions_a),
            patch.dict(os.environ, {"NOTIFICATION_OUTBOX_REPLAY_BATCH_SIZE": "2"}, clear=False),
        ):
            self.assertEqual(asyncio.run(main._register_notification_subscriber_with_replay(
                "recipient", first, 0
            )), (True, True))
        self.assertEqual(
            [call.args[0] for call in first.send_json.await_args_list],
            [
                {"type": "notification_cursor_advance", "cursor": 1},
                {"type": "notification_cursor_advance", "cursor": 2},
            ],
        )
        first.close.assert_awaited_once_with(code=1013)

        resumed = MagicMock()
        resumed.send_json = AsyncMock()
        resumed.close = AsyncMock()
        with (
            patch.object(main, "SessionLocal", self.sessions_a),
            patch.dict(os.environ, {"NOTIFICATION_OUTBOX_REPLAY_BATCH_SIZE": "2"}, clear=False),
        ):
            self.assertEqual(asyncio.run(main._register_notification_subscriber_with_replay(
                "recipient", resumed, 2
            )), (True, True))
        self.assertEqual(
            [call.args[0] for call in resumed.send_json.await_args_list],
            [
                {"type": "notification_cursor_advance", "cursor": 3},
                {"type": "notification_cursor_advance", "cursor": 4},
            ],
        )

        recovered = MagicMock()
        recovered.send_json = AsyncMock()
        with (
            patch.object(main, "SessionLocal", self.sessions_a),
            patch.dict(os.environ, {"NOTIFICATION_OUTBOX_REPLAY_BATCH_SIZE": "2"}, clear=False),
        ):
            self.assertEqual(asyncio.run(main._register_notification_subscriber_with_replay(
                "recipient", recovered, 4
            )), (True, False))
        self.assertEqual(
            [call.args[0] for call in recovered.send_json.await_args_list],
            [self._payload(5).model_dump(mode="json")],
        )
        main._remove_notification_subscriber("recipient", recovered)

    def test_replay_holds_live_delivery_behind_the_same_socket_send_lock(self):
        self._insert(event_id=1)

        async def exercise():
            replay_started = asyncio.Event()
            release_replay = asyncio.Event()
            delivered = []

            class Socket:
                async def send_json(self, payload):
                    delivered.append(payload["event_id"])
                    if payload["event_id"] == 1:
                        replay_started.set()
                        await release_replay.wait()

            socket = Socket()
            with patch.object(main, "SessionLocal", self.sessions_a):
                replay = asyncio.create_task(
                    main._register_notification_subscriber_with_replay("recipient", socket, 0)
                )
                await asyncio.wait_for(replay_started.wait(), timeout=1)
                live = asyncio.create_task(main._broadcast_notification(self._payload(2).model_dump(mode="json")))
                await asyncio.sleep(0)
                self.assertFalse(live.done(), "live fanout must wait behind replay")
                release_replay.set()
                self.assertEqual(await replay, (True, False))
                await live
            self.assertEqual(delivered, [1, 2])
            main._remove_notification_subscriber("recipient", socket)

        asyncio.run(exercise())

    def test_replay_cursor_rejects_lossy_or_malformed_values(self):
        socket = MagicMock()
        socket.query_params.get.side_effect = lambda name: {
            "missing": None,
        }.get(name)
        self.assertEqual(main._notification_replay_cursor(socket), 0)
        socket.query_params.get.side_effect = None
        for raw in ("-1", "+1", "01", "1.5", "abc", "9007199254740992"):
            socket.query_params.get.return_value = raw
            self.assertIsNone(main._notification_replay_cursor(socket), raw)
        socket.query_params.get.return_value = "9007199254740991"
        self.assertEqual(main._notification_replay_cursor(socket), 9_007_199_254_740_991)

    def test_dispatch_orders_prevent_primary_key_commit_order_gaps(self):
        """A late lower primary key is still observed by dispatch_order."""
        sent = AsyncMock()
        dispatcher = main._NotificationOutboxDispatcher(sent)
        with patch.object(main, "SessionLocal", self.sessions_a):
            asyncio.run(dispatcher.initialize())
        # Simulates PostgreSQL sequence allocation by transaction A followed
        # by B committing first: primary keys are 1 then 2, while the durable
        # lock assigns commit-safe dispatch order 2 then 1.
        self._insert(event_id=2, row_id=1, key="late-primary-key")
        self._insert(event_id=1, row_id=2, key="early-primary-key")
        with patch.object(main, "SessionLocal", self.sessions_a):
            self.assertEqual(asyncio.run(dispatcher.dispatch_once()), 2)
        self.assertEqual(
            [call.args[0]["event_id"] for call in sent.await_args_list], [1, 2]
        )
        self.assertEqual(dispatcher.cursor, 2)

    def test_dispatch_order_allocation_takes_the_singleton_row_lock(self):
        sequence = NotificationOutboxSequenceRecord(
            singleton_id=1, next_dispatch_order=41
        )
        locked = MagicMock()
        locked.one_or_none.return_value = sequence
        filtered = MagicMock()
        filtered.with_for_update.return_value = locked
        query = MagicMock()
        query.filter.return_value = filtered
        high_water_query = MagicMock()
        high_water_query.scalar.return_value = 0
        db = MagicMock()
        db.query.side_effect = [query, high_water_query]

        self.assertEqual(main._allocate_notification_dispatch_order(db), 42)
        filtered.with_for_update.assert_called_once_with()
        self.assertEqual(sequence.next_dispatch_order, 42)

    def test_allocation_repairs_a_sequence_behind_existing_events_before_award(self):
        self._insert(event_id=7)
        with self.sessions_a() as db:
            sequence = db.get(NotificationOutboxSequenceRecord, 1)
            sequence.next_dispatch_order = 2
            db.commit()

            self.assertEqual(main._allocate_notification_dispatch_order(db), 8)
            db.commit()

        with self.sessions_a() as db:
            self.assertEqual(
                db.get(NotificationOutboxSequenceRecord, 1).next_dispatch_order, 8
            )
            self.assertEqual(
                db.query(NotificationOutboxRecord).filter(
                    NotificationOutboxRecord.dispatch_order == 8
                ).count(),
                0,
            )

    def test_dispatcher_retries_same_row_after_broadcast_failure(self):
        sent = AsyncMock(side_effect=[RuntimeError("temporary"), None])
        dispatcher = main._NotificationOutboxDispatcher(sent)
        with patch.object(main, "SessionLocal", self.sessions_a):
            asyncio.run(dispatcher.initialize())
        self._insert()
        with patch.object(main, "SessionLocal", self.sessions_a):
            with self.assertRaisesRegex(RuntimeError, "temporary"):
                asyncio.run(dispatcher.dispatch_once())
            self.assertEqual(dispatcher.cursor, 0)
            asyncio.run(dispatcher.dispatch_once())
        self.assertEqual(dispatcher.cursor, 1)
        self.assertEqual(sent.await_count, 2)

    def test_dispatch_loop_recovers_after_initialization_failure(self):
        dispatcher = MagicMock()
        dispatcher.initialize = AsyncMock(side_effect=[RuntimeError("db"), None])
        dispatcher.dispatch_once = AsyncMock(side_effect=asyncio.CancelledError())
        with (
            patch.object(main, "_NotificationOutboxDispatcher", return_value=dispatcher),
            patch.object(main.asyncio, "sleep", new=AsyncMock()),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(main._notification_outbox_dispatch_loop())
        self.assertEqual(dispatcher.initialize.await_count, 2)
        dispatcher.dispatch_once.assert_awaited_once()

    def test_scheduler_start_failure_does_not_leak_notification_task(self):
        previous_task = main._notification_dispatch_task
        main._notification_dispatch_task = None
        try:
            with (
                patch.object(main, "start_sync_worker", side_effect=RuntimeError("scheduler")),
                patch.object(main, "process_role", return_value="api"),
                patch.object(main.asyncio, "create_task") as create_task,
            ):
                with self.assertRaisesRegex(RuntimeError, "scheduler"):
                    asyncio.run(main._start_runtime_background_services())
            create_task.assert_not_called()
            self.assertIsNone(main._notification_dispatch_task)
        finally:
            main._notification_dispatch_task = previous_task

    def test_readiness_fails_for_running_stale_dispatcher_then_recovers(self):
        async def check():
            task = asyncio.create_task(asyncio.sleep(60))
            main._notification_dispatch_task = task
            main._notification_dispatch_expected = True
            main._notification_dispatch_last_success_at = time.monotonic() - 6
            try:
                with patch.dict(
                    os.environ, {"NOTIFICATION_OUTBOX_STALE_SECONDS": "5"}, clear=False
                ):
                    stale_response = Response()
                    stale_result = await main.health_ready(stale_response, MagicMock())
                    main._notification_dispatch_last_success_at = time.monotonic()
                    healthy_response = Response()
                    healthy_result = await main.health_ready(healthy_response, MagicMock())
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self.assertEqual(stale_response.status_code, 503)
            self.assertEqual(stale_result, {
                "status": "not_ready",
                "checks": {"database": "ok", "notification_dispatch": "unavailable"},
            })
            self.assertEqual(healthy_response.status_code, 200)
            self.assertEqual(healthy_result, {
                "status": "ready", "checks": {"database": "ok"},
            })

        asyncio.run(check())

    def test_demo_bootstrap_idempotently_seeds_sequence_from_existing_events(self):
        self._insert(event_id=7)
        with self.sessions_a() as db:
            db.query(NotificationOutboxSequenceRecord).delete()
            db.commit()
        with patch.object(database, "engine", self.engine_a):
            database._ensure_notification_outbox_sequence()
            database._ensure_notification_outbox_sequence()
        with self.sessions_a() as db:
            sequence = db.get(NotificationOutboxSequenceRecord, 1)
            self.assertEqual(sequence.next_dispatch_order, 7)

    def test_demo_bootstrap_repairs_an_existing_sequence_behind_outbox_high_water(self):
        self._insert(event_id=7)
        with self.sessions_a() as db:
            sequence = db.get(NotificationOutboxSequenceRecord, 1)
            sequence.next_dispatch_order = 2
            db.commit()
        with patch.object(database, "engine", self.engine_a):
            database._ensure_notification_outbox_sequence()
        with self.sessions_a() as db:
            self.assertEqual(
                db.get(NotificationOutboxSequenceRecord, 1).next_dispatch_order, 7
            )

    def test_demo_bootstrap_ignores_only_a_verified_concurrent_seed_race(self):
        nested = MagicMock()
        nested.__enter__.return_value = nested
        connection = MagicMock()
        connection.begin_nested.return_value = nested
        connection.execute.side_effect = [
            IntegrityError("INSERT", {}, RuntimeError("duplicate key")),
            MagicMock(scalar_one_or_none=lambda: 1),
            MagicMock(),
        ]
        transaction = MagicMock()
        transaction.__enter__.return_value = connection
        fake_engine = MagicMock()
        fake_engine.begin.return_value = transaction
        inspect_result = MagicMock()
        inspect_result.has_table.return_value = True

        with (
            patch.object(database, "_sa_inspect", return_value=inspect_result),
            patch.object(database, "engine", fake_engine),
        ):
            database._ensure_notification_outbox_sequence()

        connection.begin_nested.assert_called_once_with()
        self.assertEqual(connection.execute.call_count, 3)

    def test_demo_bootstrap_reraises_an_unverified_seed_integrity_error(self):
        insert_error = IntegrityError("INSERT", {}, RuntimeError("constraint"))
        nested = MagicMock()
        nested.__enter__.return_value = nested
        connection = MagicMock()
        connection.begin_nested.return_value = nested
        connection.execute.side_effect = [
            insert_error,
            MagicMock(scalar_one_or_none=lambda: None),
        ]
        transaction = MagicMock()
        transaction.__enter__.return_value = connection
        fake_engine = MagicMock()
        fake_engine.begin.return_value = transaction
        inspect_result = MagicMock()
        inspect_result.has_table.return_value = True

        with (
            patch.object(database, "_sa_inspect", return_value=inspect_result),
            patch.object(database, "engine", fake_engine),
        ):
            with self.assertRaises(IntegrityError):
                database._ensure_notification_outbox_sequence()

    def test_award_has_no_immediate_broadcast_and_dispatcher_owns_delivery(self):
        with self.sessions_a() as db:
            db.add_all((
                UserRecord(id="notify-user", name="Notify", role="agent", is_active=True),
                TicketRecord(
                    id="notify-ticket", subject="Resolved", status="Resolved",
                    workflow_status="Resolved", priority="P3", assignee_id="notify-user",
                ),
            ))
            db.commit()
            with patch.object(main, "_broadcast_notification", new=AsyncMock()) as broadcast:
                asyncio.run(main._check_resolution_and_award(
                    db.get(TicketRecord, "notify-ticket"), db=db
                ))
            broadcast.assert_not_awaited()

        sent = AsyncMock()
        dispatcher = main._NotificationOutboxDispatcher(sent)
        with patch.object(main, "SessionLocal", self.sessions_a):
            asyncio.run(dispatcher.initialize())
        # A new award after initialization is delivered only through polling.
        with self.sessions_a() as db:
            db.add_all((
                UserRecord(id="notify-user-2", name="Notify Two", role="agent", is_active=True),
                TicketRecord(
                    id="notify-ticket-2", subject="Resolved", status="Resolved",
                    workflow_status="Resolved", priority="P3", assignee_id="notify-user-2",
                ),
            ))
            db.commit()
            asyncio.run(main._check_resolution_and_award(
                db.get(TicketRecord, "notify-ticket-2"), db=db
            ))
        with patch.object(main, "SessionLocal", self.sessions_a):
            asyncio.run(dispatcher.dispatch_once())
        sent.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
