import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    SyncStateRecord,
    TicketRecord,
    UserMappingRecord,
    UserRecord,
)
from app.backend.integrations import sync
from app.backend.schema import ExternalTicket


class _Adapter:
    provider_name = "test-provider"

    def __init__(self, tickets):
        self.tickets = tickets

    async def fetch_new_tickets(self, since=None):
        return self.tickets


class TicketSyncFailureIsolationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        UserRecord.__table__.create(self.engine)
        UserMappingRecord.__table__.create(self.engine)
        TicketRecord.__table__.create(self.engine)
        SyncStateRecord.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

        self.initial_cursor = datetime(2026, 7, 1, 12, 0, 0)
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                provider=_Adapter.provider_name,
                last_synced_at=self.initial_cursor,
                last_status="success",
                total_synced=4,
            ))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def _ticket(external_id, subject, updated_at):
        values = {
            "external_id": external_id,
            "subject": subject,
            "description": "Description",
            "reporter": "reporter@example.com",
            "priority": "Medium",
            "status": "Open",
            "updated_at": updated_at,
        }
        if subject is None:
            # Bypass schema validation to model malformed provider data that
            # reaches persistence and violates tickets.subject NOT NULL.
            return ExternalTicket.model_construct(**values)
        return ExternalTicket(**values)

    def test_failed_ticket_does_not_poison_later_ticket_or_sync_state(self):
        failed_at = self.initial_cursor + timedelta(minutes=1)
        persisted_at = self.initial_cursor + timedelta(minutes=2)
        adapter = _Adapter([
            self._ticket("bad-ticket", None, failed_at),
            self._ticket("good-ticket", "Valid ticket", persisted_at),
        ])

        with (
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "refresh_ticket_documents_background"),
        ):
            result = sync.sync_tickets_from_external(adapter)

        self.assertEqual(result, {"new": 1, "updated": 0, "errors": 1})
        with self.session_factory() as db:
            tickets = db.query(TicketRecord).all()
            self.assertEqual([ticket.external_id for ticket in tickets], ["good-ticket"])

            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.last_status, "error")
            self.assertEqual(
                state.last_error,
                "One or more tickets failed to persist; cursor not advanced",
            )
            self.assertEqual(state.last_synced_at, self.initial_cursor)
            self.assertEqual(state.total_synced, 5)


if __name__ == "__main__":
    unittest.main()
