import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import ExternalUserRecord, TicketRecord, UserRecord
from app.backend.integrations import sync
from app.backend.schema import ExternalTicket


class _Adapter:
    provider_name = "jira"


class AgentSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        UserRecord.__table__.create(self.engine)
        ExternalUserRecord.__table__.create(self.engine)
        TicketRecord.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add(UserRecord(
                id="existing-user",
                name="Existing Alice",
                email="alice@example.com",
            ))
            db.commit()

        self.external_agent = {
            "accountId": "jira-alice",
            "displayName": "Provider Alice",
            "emailAddress": "alice@example.com",
            "active": True,
        }

    def tearDown(self):
        self.engine.dispose()

    def _sync(self):
        with patch.object(sync, "SessionLocal", self.session_factory):
            return sync._import_external_users(
                _Adapter(),
                [self.external_agent],
            )

    def test_remote_email_match_never_links_or_changes_tickety_user(self):
        result = self._sync()

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            self.assertEqual(db.query(UserRecord).count(), 1)
            local_user = db.query(UserRecord).one()
            self.assertEqual(local_user.name, "Existing Alice")
            remote_user = db.query(ExternalUserRecord).one()
            self.assertEqual(remote_user.name, "Provider Alice")
            self.assertEqual(remote_user.email, local_user.email)

    def test_remote_refresh_updates_only_external_directory(self):
        self._sync()
        self.external_agent["displayName"] = "Provider Alice Updated"
        result = self._sync()

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)
        with self.session_factory() as db:
            self.assertEqual(db.query(UserRecord).one().name, "Existing Alice")
            self.assertEqual(
                db.query(ExternalUserRecord).one().name,
                "Provider Alice Updated",
            )

    def test_ticket_sync_never_promotes_external_assignee_to_local_owner(self):
        with self.session_factory() as db:
            action, ticket = sync._upsert_ticket(
                db,
                ExternalTicket(
                    external_id="JIRA-1",
                    subject="Provider ticket",
                    description="Provider-owned description",
                    reporter="requester@example.com",
                    priority="P3",
                    status="Open",
                    assignee_id="existing-user",
                ),
                "jira",
                overwrite=True,
            )
            self.assertEqual(action, "new")
            self.assertEqual(ticket.external_assignee_id, "existing-user")
            self.assertIsNone(ticket.assignee_id)

    def test_missing_provider_identity_is_deactivated_without_touching_local_user(self):
        self._sync()
        with patch.object(sync, "SessionLocal", self.session_factory):
            result = sync._import_external_users(_Adapter(), [])

        self.assertEqual(result["deactivated"], 1)
        with self.session_factory() as db:
            self.assertFalse(db.query(ExternalUserRecord).one().active)
            self.assertTrue(db.query(UserRecord).one().is_active)


if __name__ == "__main__":
    unittest.main()
