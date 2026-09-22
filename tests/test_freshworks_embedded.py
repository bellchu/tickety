import hashlib
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    Base,
    ExternalUserRecord,
    IntegrationBindingRecord,
    IntegrationBootstrapRecord,
    IntegrationSessionRecord,
    TicketRecord,
)
from app.backend.integrations import embedded


class FreshworksEmbeddedSessionRetirementTests(unittest.TestCase):
    binding_id = "11111111-1111-4111-8111-111111111111"

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add(IntegrationBindingRecord(
                id=self.binding_id,
                provider="freshservice",
                environment="trial",
                state="active",
                canonical_account_host="trial-example.freshservice.com",
                workspace_ids='["10"]',
                credential_reference="env://freshservice",
                expires_at=datetime.utcnow() + timedelta(days=7),
            ))
            db.add(ExternalUserRecord(
                id="external-user-99",
                binding_id=self.binding_id,
                provider="freshservice",
                external_id="99",
                user_type="agent",
                name="Provider Agent",
                active=True,
                profile_json="{}",
            ))
            db.add(TicketRecord(
                id="ticket-1",
                binding_id=self.binding_id,
                external_source="freshservice",
                external_id="42",
                external_workspace_id="10",
                external_assignee_id="99",
                subject="POC ticket",
            ))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_real_binding_agent_and_ticket_cannot_issue_a_legacy_bootstrap_code(self):
        with self.session_factory() as db:
            with self.assertRaisesRegex(
                embedded.EmbeddedAuthError,
                embedded.EMBEDDED_ACCESS_UNAVAILABLE_MESSAGE,
            ):
                embedded.issue_bootstrap_code(
                    db,
                    binding_id=self.binding_id,
                    account_host="trial-example.freshservice.com",
                    external_user_id="99",
                    workspace_id="10",
                    external_ticket_id="42",
                    ticket_updated_at=datetime.utcnow(),
                    audience="ticket_sidebar",
                )
            self.assertEqual(db.query(IntegrationBootstrapRecord).count(), 0)
            self.assertEqual(db.query(IntegrationSessionRecord).count(), 0)

    def test_previously_issued_code_and_token_are_rejected_immediately(self):
        with self.session_factory() as db:
            db.add(IntegrationBootstrapRecord(
                code_hash=hashlib.sha256(b"legacy-code").hexdigest(),
                binding_id=self.binding_id,
                external_user_id="99",
                workspace_id="10",
                audience="ticket_sidebar",
                context_json="{}",
                expires_at=datetime.utcnow() + timedelta(minutes=1),
            ))
            db.add(IntegrationSessionRecord(
                token_hash=hashlib.sha256(b"legacy-token").hexdigest(),
                binding_id=self.binding_id,
                external_user_id="99",
                workspace_id="10",
                external_ticket_id="42",
                audience="ticket_sidebar",
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            ))
            db.commit()

            with self.assertRaisesRegex(
                embedded.EmbeddedAuthError,
                embedded.EMBEDDED_ACCESS_UNAVAILABLE_MESSAGE,
            ):
                embedded.redeem_bootstrap_code(
                    db, binding_id=self.binding_id, code="legacy-code"
                )
            with self.assertRaisesRegex(
                embedded.EmbeddedAuthError,
                embedded.EMBEDDED_ACCESS_UNAVAILABLE_MESSAGE,
            ):
                embedded.authenticate_session(db, "Bearer legacy-token")

    def test_legacy_flow_cannot_be_reenabled_with_an_environment_flag(self):
        with patch.dict(
            os.environ,
            {
                "FRESHWORKS_EMBEDDED_ACCESS_ENABLED": "true",
                "FRESHWORKS_APP_BOOTSTRAP_SECRET": "s" * 32,
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                embedded.EmbeddedAuthError,
                embedded.EMBEDDED_ACCESS_UNAVAILABLE_MESSAGE,
            ):
                embedded.verify_installation_secret(
                    "ignored", binding_id=self.binding_id
                )
            with self.assertRaisesRegex(
                embedded.EmbeddedAuthError,
                embedded.EMBEDDED_ACCESS_UNAVAILABLE_MESSAGE,
            ):
                embedded.installation_secret_for_binding(self.binding_id)


if __name__ == "__main__":
    unittest.main()
