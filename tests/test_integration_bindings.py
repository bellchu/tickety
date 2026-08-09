import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    Base,
    IntegrationAuditRecord,
    IntegrationBindingRecord,
    IntegrationCapabilityRecord,
    TicketRecord,
    UserRecord,
)
from app.backend.integrations import bindings, sync
from app.backend.schema import ExternalTicket


class IntegrationBindingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add(UserRecord(id="admin", name="Admin", role="admin"))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def _create(self, db, host="trial-acme.freshservice.com"):
        with patch.dict(
            "os.environ", {"TICKETY_DEPLOYMENT_CLASS": "poc"}, clear=False
        ):
            return bindings.create_binding(
                db,
                provider="freshservice",
                environment="trial",
                canonical_account_host=host,
                workspace_ids=["1", "1", "2"],
                installation_id="installation-1",
                product_variant="ITSM",
                credential_reference="env://freshservice",
                expires_at=datetime.utcnow() + timedelta(days=14),
                actor_id="admin",
            )

    def test_trial_binding_normalizes_and_audits_without_storing_credentials(self):
        with self.session_factory() as db:
            binding = self._create(db, "https://Trial-Acme.freshservice.com/")
            self.assertEqual(binding.canonical_account_host, "trial-acme.freshservice.com")
            self.assertEqual(binding.credential_reference, "env://freshservice")
            self.assertEqual(binding.workspace_ids, '["1","2"]')
            audit = db.query(IntegrationAuditRecord).one()
            self.assertEqual(audit.action, "binding.created")
            self.assertNotIn("API", audit.details)

    def test_trial_binding_normalizes_timezone_aware_expiry_to_utc_naive(self):
        with self.session_factory() as db, patch.dict(
            "os.environ", {"TICKETY_DEPLOYMENT_CLASS": "poc"}, clear=False
        ):
            binding = bindings.create_binding(
                db,
                provider="freshservice",
                environment="trial",
                canonical_account_host="trial-acme.freshservice.com",
                workspace_ids=[],
                installation_id=None,
                product_variant="ITSM",
                credential_reference="env://freshservice",
                expires_at=datetime.now(timezone.utc) + timedelta(days=14),
                actor_id="admin",
            )

        self.assertIsNone(binding.expires_at.tzinfo)
        self.assertGreater(binding.expires_at, datetime.utcnow())

    def test_host_paths_and_non_freshservice_hosts_are_rejected(self):
        for host in (
            "https://trial-acme.freshservice.com/admin",
            "https://attacker.example",
            "https://freshservice.com",
            "http://trial-acme.freshservice.com",
        ):
            with self.subTest(host=host), self.assertRaises(bindings.BindingValidationError):
                bindings.normalize_freshservice_host(host)

    def test_trial_binding_requires_poc_deployment_and_bounded_expiry(self):
        with self.session_factory() as db, patch.dict(
            "os.environ", {"TICKETY_DEPLOYMENT_CLASS": "production"}, clear=False
        ):
            with self.assertRaisesRegex(bindings.BindingValidationError, "POC"):
                bindings.create_binding(
                    db,
                    provider="freshservice",
                    environment="trial",
                    canonical_account_host="trial-acme.freshservice.com",
                    workspace_ids=[],
                    installation_id=None,
                    product_variant="ITSM",
                    credential_reference="env://freshservice",
                    expires_at=datetime.utcnow() + timedelta(days=14),
                    actor_id="admin",
                )

    async def test_validation_snapshots_capabilities_before_activation(self):
        with self.session_factory() as db:
            binding = self._create(db)
            adapter = AsyncMock()
            adapter.probe_capabilities.return_value = {
                "ticket.read": {"status": "supported", "http_status": 200},
                "ticket.create": {"status": "unknown"},
                "freshworks.full_page_app": {"status": "unknown"},
            }
            with (
                patch.dict("os.environ", {"TICKETY_DEPLOYMENT_CLASS": "poc"}, clear=False),
                patch.object(bindings, "get_adapter", return_value=adapter),
                patch.object(bindings, "clear_adapter_cache"),
            ):
                result = await bindings.validate_binding(db, binding, actor_id="admin")
                activated = bindings.activate_binding(db, binding, actor_id="admin")

            self.assertTrue(result["ready_for_activation"])
            self.assertEqual(activated.state, "active")
            capabilities = {
                row.capability: row.status
                for row in db.query(IntegrationCapabilityRecord).all()
            }
            self.assertEqual(capabilities["ticket.read"], "supported")
            self.assertEqual(capabilities["ticket.create"], "unknown")

    async def test_activation_fails_closed_without_ticket_read(self):
        with self.session_factory() as db:
            binding = self._create(db)
            adapter = AsyncMock()
            adapter.probe_capabilities.return_value = {
                "ticket.read": {"status": "restricted", "http_status": 403},
            }
            with (
                patch.dict("os.environ", {"TICKETY_DEPLOYMENT_CLASS": "poc"}, clear=False),
                patch.object(bindings, "get_adapter", return_value=adapter),
                patch.object(bindings, "clear_adapter_cache"),
            ):
                result = await bindings.validate_binding(db, binding, actor_id="admin")
                with self.assertRaisesRegex(bindings.BindingValidationError, "ticket.read"):
                    bindings.activate_binding(db, binding, actor_id="admin")
            self.assertFalse(result["ready_for_activation"])

    async def test_external_ticket_identity_is_scoped_by_binding(self):
        ticket = ExternalTicket(
            external_id="42",
            subject="Trial ticket",
            description="Synthetic",
            reporter="poc@example.test",
            priority="P3",
            status="Open",
        )
        with self.session_factory() as db:
            first, _ = sync._upsert_ticket(
                db, ticket, "freshservice", binding_id="binding-a"
            )
            second, _ = sync._upsert_ticket(
                db, ticket, "freshservice", binding_id="binding-b"
            )
            rows = db.query(TicketRecord).order_by(TicketRecord.binding_id).all()
        self.assertEqual((first, second), ("new", "new"))
        self.assertEqual(
            [(row.binding_id, row.external_id) for row in rows],
            [("binding-a", "42"), ("binding-b", "42")],
        )

    def test_expiry_suspends_active_work_without_touching_other_bindings(self):
        with self.session_factory() as db:
            binding = self._create(db)
            binding.state = "active"
            binding.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
            with patch.object(bindings, "clear_adapter_cache") as clear:
                count = bindings.expire_due_bindings(db)
            db.refresh(binding)
            self.assertEqual(count, 1)
            self.assertEqual(binding.state, "expired")
            clear.assert_called_once_with(binding.id)


if __name__ == "__main__":
    unittest.main()
