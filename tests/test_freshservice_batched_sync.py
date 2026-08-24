import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import Base, SyncStateRecord, TicketRecord
from app.backend.integrations import sync
from app.backend.integrations.freshservice import FreshserviceRateLimited
from app.backend.schema import ExternalTicket


class _BatchedFreshserviceAdapter:
    provider_name = "freshservice"

    def __init__(self, recent, historical, *, remaining=500):
        self.recent = recent
        self.historical = historical
        self.remaining = remaining
        self.calls = []
        self.conversation_calls = []

    async def fetch_ticket_page(
        self,
        *,
        since,
        page,
        workspace_index,
        order_type,
        include_resources,
    ):
        lane = "history" if since.year == 1970 else "recent"
        self.calls.append((lane, page, order_type, include_resources))
        tickets = self.historical if lane == "history" else self.recent
        return SimpleNamespace(
            tickets=tickets,
            has_next_page=lane == "history",
            workspace_count=1,
        )

    async def fetch_ticket_conversations(self, external_id, max_pages=None):
        self.conversation_calls.append(external_id)
        return []

    def rate_limit_snapshot(self):
        return {"total": 500, "remaining": self.remaining, "used": 1}

    def should_pause_requests(self):
        return self.remaining <= 10


class _RateLimitedAdapter(_BatchedFreshserviceAdapter):
    async def fetch_ticket_page(self, **kwargs):
        self.calls.append(("attempt", kwargs["page"], kwargs["order_type"], False))
        raise FreshserviceRateLimited(75)


class FreshserviceBatchedSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.now = datetime.utcnow().replace(microsecond=0)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def _ticket(external_id, created_at, updated_at):
        return ExternalTicket(
            external_id=external_id,
            subject=f"Ticket {external_id}",
            description="Description",
            reporter="requester@example.com",
            priority="P3",
            status="Open",
            created_at=created_at,
            updated_at=updated_at,
        )

    def _run(self, adapter):
        env = {
            "FRESHSERVICE_RECENT_PAGES_PER_SYNC": "1",
            "FRESHSERVICE_HISTORY_PAGES_PER_SYNC": "1",
            "FRESHSERVICE_CONVERSATIONS_PER_SYNC": "1",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "refresh_ticket_documents_if_indexed"),
        ):
            return sync.sync_tickets_from_external(adapter)

    def test_recent_page_is_persisted_before_slow_history_and_hydrated_first(self):
        recent = self._ticket("recent", self.now, self.now)
        historical = self._ticket(
            "historical",
            self.now - timedelta(days=500),
            self.now - timedelta(days=400),
        )
        adapter = _BatchedFreshserviceAdapter([recent], [historical])

        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["recent_pages"], 1)
        self.assertEqual(result["history_pages"], 1)
        self.assertEqual(adapter.calls, [
            ("recent", 1, "asc", False),
            ("history", 1, "asc", False),
        ])
        self.assertEqual(adapter.conversation_calls, ["recent"])
        with self.session_factory() as db:
            self.assertEqual(
                {row.external_id for row in db.query(TicketRecord).all()},
                {"recent", "historical"},
            )
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.last_status, "success")
            self.assertEqual(state.history_page, 2)
            self.assertFalse(state.history_complete)
            self.assertEqual(state.history_processed, 1)
            self.assertEqual(state.conversations_processed, 1)
            self.assertIsNotNone(state.last_synced_at)
            self.assertIsNone(state.run_token)

    def test_retry_after_is_persisted_as_a_clean_throttle_not_an_error(self):
        adapter = _RateLimitedAdapter([], [])

        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["throttled"], 1)
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.last_status, "throttled")
            self.assertIsNone(state.last_error)
            self.assertGreater(
                state.next_retry_at,
                datetime.utcnow() + timedelta(seconds=60),
            )
            self.assertIsNone(state.run_token)

    def test_live_lease_defers_overlapping_manual_or_scheduled_run(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                run_token="active-run",
                run_started_at=datetime.utcnow(),
                last_status="running",
            ))
            db.commit()
        adapter = _BatchedFreshserviceAdapter([], [])

        result = self._run(adapter)

        self.assertEqual(result["deferred"], 1)
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
