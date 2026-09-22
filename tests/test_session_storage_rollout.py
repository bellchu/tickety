import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, SessionRecord, TicketRecord, UserRecord


class SessionStorageRolloutTests(unittest.TestCase):
    """Cross-version browser-session compatibility without digest replay."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([
                UserRecord(id="legacy", name="Legacy", role="agent", is_active=True),
                UserRecord(id="hashed", name="Hashed", role="agent", is_active=True),
                SessionRecord(
                    token_hash="legacy-browser-token",
                    user_id="legacy",
                    expires_at=datetime.utcnow() + timedelta(hours=1),
                ),
                SessionRecord(
                    token_hash=main.session_token_digest("hashed-browser-token"),
                    user_id="hashed",
                    expires_at=datetime.utcnow() + timedelta(hours=1),
                ),
                TicketRecord(
                    id="hashed-ticket",
                    subject="Session-bound analysis",
                    assignee_id="hashed",
                ),
            ])
            db.commit()
        self.session_local = patch.object(main, "SessionLocal", self.sessions)
        self.session_local.start()
        self.previous_notification_subscribers = list(main._notification_subscribers)
        self.previous_notification_activity = dict(main._notification_subscriber_activity)
        self.previous_notification_locks = dict(main._notification_subscriber_send_locks)
        main._notification_subscribers.clear()
        main._notification_subscriber_activity.clear()
        main._notification_subscriber_send_locks.clear()

    def tearDown(self):
        main._notification_subscribers[:] = self.previous_notification_subscribers
        main._notification_subscriber_activity.clear()
        main._notification_subscriber_activity.update(self.previous_notification_activity)
        main._notification_subscriber_send_locks.clear()
        main._notification_subscriber_send_locks.update(self.previous_notification_locks)
        self.session_local.stop()
        self.engine.dispose()

    def test_api_lookup_accepts_legacy_and_hashed_sessions_but_not_digest_replay(self):
        with self.sessions() as db:
            for token, expected in (
                ("legacy-browser-token", "legacy"),
                ("hashed-browser-token", "hashed"),
            ):
                request = SimpleNamespace(cookies={main.SESSION_COOKIE: token})
                user = main._resolve_request_user(request, db, allow_demo=False)
                self.assertEqual(user.id, expected)

            digest = main.session_token_digest("hashed-browser-token")
            replay = SimpleNamespace(cookies={main.SESSION_COOKIE: digest})
            self.assertIsNone(main._resolve_request_user(replay, db, allow_demo=False))

    def test_compat_mode_writes_raw_until_operator_switches_to_hashed(self):
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "test"}
        with self.sessions() as db:
            with patch.dict(os.environ, {"SESSION_STORAGE_MODE": "compat"}):
                compat_token = main._create_session(db, "legacy", request)
            self.assertIsNotNone(db.get(SessionRecord, compat_token))

            with patch.dict(os.environ, {"SESSION_STORAGE_MODE": "hashed"}):
                hashed_token = main._create_session(db, "legacy", request)
            self.assertIsNone(db.get(SessionRecord, hashed_token))
            self.assertIsNotNone(db.get(SessionRecord, main.session_token_digest(hashed_token)))

    def test_logout_deletes_a_legacy_session_with_the_same_bounded_lookup(self):
        request = SimpleNamespace(cookies={main.SESSION_COOKIE: "legacy-browser-token"})
        with self.sessions() as db:
            asyncio.run(main.logout(request, db))
            self.assertIsNone(db.get(SessionRecord, "legacy-browser-token"))

    def test_websocket_auth_accepts_legacy_session_and_rejects_digest_replay(self):
        legacy_socket = SimpleNamespace(cookies={main.SESSION_COOKIE: "legacy-browser-token"})
        self.assertEqual(main._websocket_user(legacy_socket).id, "legacy")

        digest_socket = SimpleNamespace(
            cookies={main.SESSION_COOKIE: main.session_token_digest("hashed-browser-token")}
        )
        self.assertIsNone(main._websocket_user(digest_socket))

    def test_notification_fanout_revokes_a_logged_out_socket_before_delivery(self):
        class Socket:
            cookies = {main.SESSION_COOKIE: "hashed-browser-token"}
            send_json = AsyncMock()
            close = AsyncMock()

        socket = Socket()
        self.assertTrue(main._register_notification_subscriber("hashed", socket))

        # This is the same durable session-row deletion performed by logout.
        with self.sessions() as db:
            session = main._session_for_browser_token(db, "hashed-browser-token")
            db.delete(session)
            db.commit()

        asyncio.run(main._broadcast_notification({"user_id": "hashed", "type": "points_awarded"}))

        socket.send_json.assert_not_awaited()
        socket.close.assert_awaited_once_with(code=1008)
        self.assertNotIn(("hashed", socket), main._notification_subscribers)

    def test_notification_fanout_revokes_a_deactivated_user_before_delivery(self):
        class Socket:
            cookies = {main.SESSION_COOKIE: "hashed-browser-token"}
            send_json = AsyncMock()
            close = AsyncMock()

        socket = Socket()
        self.assertTrue(main._register_notification_subscriber("hashed", socket))
        with self.sessions() as db:
            db.get(UserRecord, "hashed").is_active = False
            db.commit()

        asyncio.run(main._broadcast_notification({"user_id": "hashed", "type": "points_awarded"}))

        socket.send_json.assert_not_awaited()
        socket.close.assert_awaited_once_with(code=1008)
        self.assertNotIn(("hashed", socket), main._notification_subscribers)

    def test_notification_heartbeat_cannot_extend_a_logged_out_socket(self):
        class Socket:
            def __init__(self, sessions):
                self.cookies = {main.SESSION_COOKIE: "hashed-browser-token"}
                self.query_params = {}
                self.accept = AsyncMock()
                self.close = AsyncMock()
                self.send_json = AsyncMock()
                self._sessions = sessions
                self._received = False

            async def receive_text(self):
                if self._received:
                    raise AssertionError("revoked socket must not await another heartbeat")
                self._received = True
                with self._sessions() as db:
                    session = main._session_for_browser_token(db, "hashed-browser-token")
                    db.delete(session)
                    db.commit()
                return "heartbeat"

        socket = Socket(self.sessions)
        with (
            patch.object(main, "_websocket_origin_allowed", return_value=True),
            patch.object(main.settings_module, "is_demo_mode", return_value=False),
        ):
            asyncio.run(main.ws_notifications(socket))

        socket.accept.assert_awaited_once()
        socket.send_json.assert_not_awaited()
        socket.close.assert_awaited_once_with(code=1008)
        self.assertEqual(main._notification_subscribers, [])

    def test_notification_replay_cannot_cross_a_session_revocation(self):
        class Socket:
            cookies = {main.SESSION_COOKIE: "hashed-browser-token"}
            send_json = AsyncMock()
            close = AsyncMock()

        def revoke_before_replay(*_args):
            with self.sessions() as db:
                session = main._session_for_browser_token(db, "hashed-browser-token")
                db.delete(session)
                db.commit()
            return [(
                1,
                json.dumps({
                    "event_id": 1,
                    "ticket_id": "hashed-ticket",
                    "ticket_subject": "Session-bound analysis",
                    "user_id": "hashed",
                    "user_name": "Hashed",
                    "points_earned": 1,
                    "new_total": 1,
                    "new_tier": 1,
                    "tier_promoted": False,
                    "new_momentum": 1,
                }),
            )], False

        socket = Socket()
        with patch.object(main, "_notification_outbox_replay_after", side_effect=revoke_before_replay):
            self.assertEqual(
                asyncio.run(main._register_notification_subscriber_with_replay("hashed", socket, 0)),
                (False, False),
            )

        socket.send_json.assert_not_awaited()
        socket.close.assert_awaited_once_with(code=1008)
        self.assertNotIn(("hashed", socket), main._notification_subscribers)

    def test_ticket_stream_blocks_a_completion_after_session_revocation(self):
        class Socket:
            cookies = {main.SESSION_COOKIE: "hashed-browser-token"}
            accept = AsyncMock()
            close = AsyncMock()
            send_json = AsyncMock()

        async def revoke_then_complete(*_args, **_kwargs):
            with self.sessions() as db:
                session = main._session_for_browser_token(db, "hashed-browser-token")
                db.delete(session)
                db.commit()
            return {"private": "must not reach a logged-out socket"}

        socket = Socket()
        with (
            patch.object(main, "_websocket_origin_allowed", return_value=True),
            patch.object(main.settings_module, "is_demo_mode", return_value=False),
            patch.object(main, "_reserve_ai_request"),
            patch.object(main, "_run_ticket_analysis", side_effect=revoke_then_complete),
        ):
            asyncio.run(main.ws_ticket_stream(socket, "hashed-ticket"))

        self.assertEqual(socket.send_json.await_count, 1)
        self.assertEqual(socket.send_json.await_args.args[0]["type"], "progress")
        socket.close.assert_awaited_once_with(code=1008)

    def test_invalid_storage_mode_fails_closed(self):
        with patch.dict(os.environ, {"SESSION_STORAGE_MODE": "raw-and-hashed"}):
            with self.assertRaisesRegex(ValueError, "SESSION_STORAGE_MODE"):
                main.settings_module.session_storage_mode()
