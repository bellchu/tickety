import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    IntegrationAuditRecord,
    IntegrationBindingRecord,
    IntegrationCapabilityRecord,
    SyncStateRecord,
    TicketRecord,
    UserRecord,
)
from app.backend.integrations import bindings, registry, sync
from app.backend.schema import (
    AutomaticAIEnableRequest,
    AutomaticAIPauseRequest,
    ExternalTicket,
)


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
            self.assertEqual(
                registry._binding_config(binding)["FRESHSERVICE_WORKSPACE_IDS"],
                "1,2",
            )
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
                "integration.mode": {"status": "supported", "mode": "read_only"},
                "ticket.read": {"status": "supported", "http_status": 200},
                "ticket.create": {"status": "unsupported", "reason": "read_only_sidecar"},
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
            self.assertEqual(capabilities["integration.mode"], "supported")
            self.assertEqual(capabilities["ticket.create"], "unsupported")

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

    def test_automatic_ai_enable_is_explicit_atomic_and_audited(self):
        with self.session_factory() as db:
            binding = self._create(db)
            binding.state = "active"
            db.add_all([
                IntegrationCapabilityRecord(
                    binding_id=binding.id,
                    capability="ticket.read",
                    status="supported",
                ),
                IntegrationCapabilityRecord(
                    binding_id=binding.id,
                    capability="conversation.read",
                    status="supported",
                ),
            ])
            digest = "sha256:" + "a" * 64
            common = {
                "status": "approved",
                "capability_version": binding.capability_version,
                "evidence_digest": digest,
            }
            db.add_all([
                IntegrationAuditRecord(
                    binding_id=binding.id,
                    action="automatic_ai.rollout.phase0.approved",
                    actor_id="admin",
                    details=json.dumps({
                        **common,
                        "schema_verified": True,
                        "retention_verified": True,
                        "read_only_verified": True,
                        "negative_egress_passed": True,
                    }),
                ),
                IntegrationAuditRecord(
                    binding_id=binding.id,
                    action="automatic_ai.rollout.phase1.approved",
                    actor_id="admin",
                    details=json.dumps({
                        **common,
                        "duration_hours": 24,
                        "all_tickets": True,
                        "critical_errors": 0,
                        "identity_hash_coverage": 1.0,
                        "projection_failure_rate": 0.0,
                    }),
                ),
                IntegrationAuditRecord(
                    binding_id=binding.id,
                    action="automatic_ai.rollout.phase2.approved",
                    actor_id="admin",
                    details=json.dumps({
                        **common,
                        "duration_hours": 24,
                        "all_revisions": True,
                        "eligibility_agreement": 1.0,
                        "historical_seed_claims": 0,
                        "two_worker_equal": True,
                        "inventory_complete": True,
                        "inventory_completed_at": datetime.utcnow().isoformat(),
                    }),
                ),
            ])
            db.commit()
            user = db.query(UserRecord).filter(UserRecord.id == "admin").one()

            response = main.enable_integration_automatic_ai(
                binding.id,
                AutomaticAIEnableRequest(
                    reason="approved realtime canary",
                    expected_generation=0,
                ),
                db,
                user,
            )

            self.assertTrue(response["automatic_ai_enabled"])
            self.assertEqual(response["automatic_ai_lookback_days"], 7)
            state = db.query(SyncStateRecord).filter(
                SyncStateRecord.binding_id == binding.id
            ).one()
            self.assertEqual(state.automatic_ai_generation, 1)
            audit = db.query(IntegrationAuditRecord).filter(
                IntegrationAuditRecord.action == "automatic_ai_enabled"
            ).one()
            self.assertIn("approved realtime canary", audit.details)
            self.assertEqual(json.loads(audit.details)["lookback_days"], 7)

            db.add(TicketRecord(
                id="queued-external",
                binding_id=binding.id,
                external_source="freshservice",
                external_id="9001",
                subject="Queued external ticket",
                ai_status="queued",
                ai_claim_id="claim-1",
                ai_requested_artifacts="triage",
            ))
            db.commit()
            paused = main.pause_integration_automatic_ai(
                binding.id,
                AutomaticAIPauseRequest(
                    reason="emergency privacy stop",
                    expected_generation=1,
                ),
                db,
                user,
            )
            self.assertFalse(paused["automatic_ai_enabled"])
            self.assertEqual(paused["revoked_requests"], 1)
            queued = db.query(TicketRecord).filter(
                TicketRecord.id == "queued-external"
            ).one()
            self.assertEqual(queued.ai_status, "paused")
            self.assertIsNone(queued.ai_claim_id)
            pause_audit = db.query(IntegrationAuditRecord).filter(
                IntegrationAuditRecord.action == "automatic_ai_paused"
            ).one()
            self.assertIn("emergency privacy stop", pause_audit.details)

    def test_automatic_ai_enable_fails_closed_without_rollout_evidence(self):
        with self.session_factory() as db:
            binding = self._create(db)
            binding.state = "active"
            db.add_all([
                IntegrationCapabilityRecord(
                    binding_id=binding.id,
                    capability="ticket.read",
                    status="supported",
                ),
                IntegrationCapabilityRecord(
                    binding_id=binding.id,
                    capability="conversation.read",
                    status="supported",
                ),
            ])
            db.commit()
            user = db.query(UserRecord).filter(UserRecord.id == "admin").one()

            with self.assertRaises(main.HTTPException) as raised:
                main.enable_integration_automatic_ai(
                    binding.id,
                    AutomaticAIEnableRequest(
                        reason="must remain disabled",
                        expected_generation=0,
                    ),
                    db,
                    user,
                )

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail,
                "automatic_ai_rollout_evidence_missing",
            )
            self.assertEqual(db.query(SyncStateRecord).count(), 0)


if __name__ == "__main__":
    unittest.main()
