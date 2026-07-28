import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import TicketRecord, UserMappingRecord, UserRecord
from app.backend.integrations import sync


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
        UserMappingRecord.__table__.create(self.engine)
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

    def _sync(self, options):
        with patch.object(sync, "SessionLocal", self.session_factory):
            return sync._import_external_agents(
                _Adapter(),
                [self.external_agent],
                options=options,
            )

    def test_sync_missing_does_not_duplicate_an_email_match(self):
        result = self._sync({
            "mode": "sync",
            "create_missing": True,
            "merge_existing": False,
            "reassign_tickets": False,
        })

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["conflicts"], 1)
        self.assertIn("enable merge", result["conflict_details"][0])
        with self.session_factory() as db:
            self.assertEqual(db.query(UserRecord).count(), 1)
            self.assertEqual(db.query(UserMappingRecord).count(), 0)

    def test_merge_links_the_existing_email_match(self):
        result = self._sync({
            "mode": "merge",
            "create_missing": True,
            "merge_existing": True,
            "reassign_tickets": False,
        })

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["merged"], 1)
        self.assertEqual(result["conflicts"], 0)
        with self.session_factory() as db:
            self.assertEqual(db.query(UserRecord).count(), 1)
            mapping = db.query(UserMappingRecord).one()
            self.assertEqual(mapping.tickety_user_id, "existing-user")


if __name__ == "__main__":
    unittest.main()
