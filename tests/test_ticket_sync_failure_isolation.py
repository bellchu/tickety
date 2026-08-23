import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    SyncStateRecord,
    TicketRecord,
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

    async def fetch_tickets_since(self, since=None):
        return self.tickets


class _FreshserviceAdapter(_Adapter):
    provider_name = "freshservice"


class TicketSyncFailureIsolationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        UserRecord.__table__.create(self.engine)
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

    def test_final_commit_failure_rolls_back_before_recording_sync_state(self):
        """The outer handler must not query through a failed transaction."""
        db = self.session_factory()
        original_commit = db.commit
        original_query = db.query
        original_rollback = db.rollback
        calls = {"commit": 0, "rollback": 0, "requires_rollback": False}

        def commit():
            calls["commit"] += 1
            # The first commit marks this sync as running. Fail its final
            # commit as a database would, then allow the error-state commit.
            if calls["commit"] == 2:
                calls["requires_rollback"] = True
                raise SQLAlchemyError("final sync commit failed")
            return original_commit()

        def rollback():
            calls["rollback"] += 1
            calls["requires_rollback"] = False
            return original_rollback()

        def query(*args, **kwargs):
            if calls["requires_rollback"]:
                raise AssertionError("sync state was queried before rollback")
            return original_query(*args, **kwargs)

        db.commit = commit
        db.rollback = rollback
        db.query = query
        try:
            with patch.object(sync, "SessionLocal", return_value=db):
                result = sync.sync_tickets_from_external(_Adapter([]))
        finally:
            # sync_tickets_from_external closes the session, but restore the
            # instance methods so test cleanup cannot retain instrumentation.
            db.commit = original_commit
            db.rollback = original_rollback
            db.query = original_query

        self.assertEqual(result, {"new": 0, "updated": 0, "errors": 1})
        self.assertGreaterEqual(calls["rollback"], 1)
        with self.session_factory() as check_db:
            state = check_db.query(SyncStateRecord).one()
            self.assertEqual(state.last_status, "error")
            self.assertEqual(state.last_error, "sync_failed:SQLAlchemyError")
            self.assertEqual(state.last_synced_at, self.initial_cursor)
            self.assertEqual(state.total_synced, 4)

    def test_manual_fetch_updates_changed_freshservice_status_without_overwrite(self):
        source_updated_at = self.initial_cursor + timedelta(minutes=3)
        with self.session_factory() as db:
            db.add(TicketRecord(
                id="existing-ticket",
                subject="Keep local subject",
                description="Keep local description",
                reporter="reporter@example.com",
                priority="P3",
                status="Open",
                workflow_status="Open",
                external_source="freshservice",
                external_id="freshservice-123",
                external_status="Open",
                external_updated_at=self.initial_cursor,
            ))
            db.commit()

        changed_at_source = ExternalTicket(
            external_id="freshservice-123",
            subject="Changed source subject",
            description="Changed source description",
            reporter="source@example.com",
            priority="P1",
            status="Resolved",
            updated_at=source_updated_at,
            resolved_at=source_updated_at,
        )

        with (
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "refresh_ticket_documents_if_indexed"),
        ):
            result = sync.fetch_tickets_by_days(
                _FreshserviceAdapter([changed_at_source]),
                days=7,
                overwrite=False,
            )

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).filter(
                TicketRecord.external_source == "freshservice"
            ).one()
            self.assertEqual(ticket.external_status, "Resolved")
            self.assertEqual(ticket.status, "Closed")
            self.assertEqual(ticket.workflow_status, "Closed")
            self.assertEqual(ticket.external_updated_at, source_updated_at)
            self.assertEqual(ticket.external_resolved_at, source_updated_at)
            self.assertEqual(ticket.resolved_at, source_updated_at)
            # overwrite=False still protects non-status provider fields.
            self.assertEqual(ticket.subject, "Keep local subject")
            self.assertEqual(ticket.description, "Keep local description")
            self.assertEqual(ticket.priority, "P3")
            state = db.query(SyncStateRecord).filter(
                SyncStateRecord.provider == "freshservice"
            ).one()
            self.assertEqual(state.last_status, "success")
            self.assertEqual(state.total_synced, 1)


if __name__ == "__main__":
    unittest.main()
