import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    Base,
    IntegrationBindingRecord,
    IntegrationBootstrapRecord,
    IntegrationSessionRecord,
    TicketRecord,
    UserMappingRecord,
    UserRecord,
)
from app.backend.integrations import embedded


class FreshworksEmbeddedSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add(UserRecord(id="agent-1", name="Agent", role="agent", is_active=True))
            db.add(IntegrationBindingRecord(
                id="11111111-1111-4111-8111-111111111111",
                provider="freshservice",
                environment="trial",
                state="active",
                canonical_account_host="trial-acme.freshservice.com",
                workspace_ids='["10"]',
                credential_reference="env://freshservice",
                expires_at=datetime.utcnow() + timedelta(days=7),
            ))
            db.flush()
            db.add(UserMappingRecord(
                binding_id="11111111-1111-4111-8111-111111111111",
                tickety_user_id="agent-1",
                external_source="freshservice",
                external_assignee_id="99",
            ))
            db.add(TicketRecord(
                id="ticket-1",
                binding_id="11111111-1111-4111-8111-111111111111",
                external_source="freshservice",
                external_id="42",
                external_workspace_id="10",
                assignee_id="agent-1",
                subject="POC ticket",
            ))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_one_time_code_issues_hashed_ticket_scoped_session(self):
        with self.session_factory() as db, patch.dict(
            "os.environ", {"FRESHWORKS_APP_BOOTSTRAP_SECRET": "s" * 32}
        ):
            embedded.verify_installation_secret("s" * 32)
            code, _expires_at = embedded.issue_bootstrap_code(
                db,
                binding_id="11111111-1111-4111-8111-111111111111",
                account_host="https://trial-acme.freshservice.com",
                external_user_id="99",
                workspace_id="10",
                external_ticket_id="42",
                ticket_updated_at=datetime.utcnow(),
                audience="ticket_sidebar",
            )
            stored = db.query(IntegrationBootstrapRecord).one()
            self.assertNotEqual(stored.code_hash, code)

            token, session = embedded.redeem_bootstrap_code(
                db,
                binding_id="11111111-1111-4111-8111-111111111111",
                code=code,
            )
            self.assertEqual(session.external_ticket_id, "42")
            self.assertNotEqual(session.token_hash, token)
            self.assertEqual(db.query(IntegrationSessionRecord).count(), 1)
            with self.assertRaises(embedded.EmbeddedAuthError):
                embedded.redeem_bootstrap_code(
                    db,
                    binding_id="11111111-1111-4111-8111-111111111111",
                    code=code,
                )

            principal = embedded.authenticate_session(db, f"Bearer {token}")
            embedded.require_ticket_scope(principal, "42")
            with self.assertRaises(embedded.EmbeddedAuthError):
                embedded.require_ticket_scope(principal, "43")

    def test_bootstrap_rejects_cross_workspace_context(self):
        with self.session_factory() as db, self.assertRaises(embedded.EmbeddedAuthError):
            embedded.issue_bootstrap_code(
                db,
                binding_id="11111111-1111-4111-8111-111111111111",
                account_host="trial-acme.freshservice.com",
                external_user_id="99",
                workspace_id="11",
                external_ticket_id="42",
                ticket_updated_at=None,
                audience="ticket_sidebar",
            )

    def test_installation_secret_fails_closed(self):
        with patch.dict("os.environ", {"FRESHWORKS_APP_BOOTSTRAP_SECRET": "short"}):
            with self.assertRaises(embedded.EmbeddedAuthError):
                embedded.verify_installation_secret("short")


if __name__ == "__main__":
    unittest.main()
