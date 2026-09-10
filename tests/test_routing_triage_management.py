import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import directory_service, main, routing_rules
from app.backend.brain import IntelligenceEngine
from app.backend.database import (
    AgentResolverTeamMappingAuditRecord,
    AgentResolverTeamMappingRecord,
    AIArtifactRecord,
    Base,
    ExternalUserRecord,
    RoutingRuleAuditRecord,
    RoutingRuleRecord,
    TicketRecord,
    UserRecord,
    get_db,
)


class RoutingManagementEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add_all([
                UserRecord(id="admin", name="Admin", role="admin", is_active=True),
                UserRecord(id="supervisor", name="Supervisor", role="supervisor", is_active=True),
                UserRecord(id="agent", name="Agent", role="agent", is_active=True),
                UserRecord(id="inactive", name="Inactive", role="agent", is_active=False),
            ])
            db.commit()

        def override_db():
            with self.session_factory() as db:
                yield db

        main.app.dependency_overrides[get_db] = override_db
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.middleware_roles_patch = patch.object(main, "_roles_required_for_request", return_value=None)
        self.middleware_roles_patch.start()
        self.demo_patch = patch.object(main.settings_module, "is_demo_mode", return_value=False)
        self.demo_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.demo_patch.stop()
        self.middleware_roles_patch.stop()
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _as_role(self, role):
        def current_user():
            with self.session_factory() as db:
                return db.get(UserRecord, role)

        main.app.dependency_overrides[main.get_protected_ai_user] = current_user

    def test_status_is_safe_for_supervisor_and_automation_write_is_admin_only(self):
        self._as_role("supervisor")
        with (
            patch.object(main.settings_module, "get_bool", side_effect=lambda key: key == "AUTO_TRIAGE_ENABLED"),
            patch.object(main.settings_module, "automation_enabled", side_effect=lambda key, *_args: key == "AUTO_TRIAGE_ENABLED"),
        ):
            response = self.client.get("/admin/routing-triage/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        body = response.json()
        self.assertTrue(body["auto_triage"]["effective"])
        self.assertFalse(body["auto_routing"]["effective"])
        self.assertFalse(body["automation_controls_editable"])
        self.assertTrue(body["rule_controls_editable"])
        self.assertFalse(body["catalog_mapping_write_available"])
        self.assertNotIn("prompt", body)

        forbidden = self.client.put("/admin/routing-triage/automation", json={
            "auto_triage_enabled": True,
            "auto_routing_enabled": True,
        })
        self.assertEqual(forbidden.status_code, 403)

        self._as_role("admin")
        with (
            patch.object(main.settings_module, "update_settings") as update,
            patch.object(main.settings_module, "get_bool", return_value=True),
            patch.object(main.settings_module, "automation_enabled", return_value=True),
        ):
            updated = self.client.put("/admin/routing-triage/automation", json={
                "auto_triage_enabled": True,
                "auto_routing_enabled": True,
            })
        self.assertEqual(updated.status_code, 200)
        update.assert_called_once_with({
            "AUTO_TRIAGE_ENABLED": "true",
            "AUTO_ROUTE_ENABLED": "true",
        }, actor_id="admin")

    def test_admin_maps_agent_to_multiple_teams_with_concurrency_and_audit(self):
        self._as_role("supervisor")
        listed = self.client.get("/admin/agent-team-mappings")
        self.assertEqual(listed.status_code, 200)
        self.assertFalse(listed.json()["editable"])
        self.assertNotIn("email", listed.text)
        forbidden = self.client.put("/admin/agent-team-mappings/agent", json={
            "resolver_groups": ["APPLICATION_OPERATIONS"],
            "expected_resolver_groups": [],
        })
        self.assertEqual(forbidden.status_code, 403)

        self._as_role("admin")
        created = self.client.put("/admin/agent-team-mappings/agent", json={
            "resolver_groups": ["APPLICATION_OPERATIONS", "IDENTITY_ACCESS"],
            "expected_resolver_groups": [],
        })
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["resolver_groups"], ["APPLICATION_OPERATIONS", "IDENTITY_ACCESS"])

        stale = self.client.put("/admin/agent-team-mappings/agent", json={
            "resolver_groups": ["SOFTWARE_ENGINEERING"],
            "expected_resolver_groups": [],
        })
        self.assertEqual(stale.status_code, 409)

        with self.session_factory() as db:
            groups = sorted(row.resolver_group for row in db.query(AgentResolverTeamMappingRecord).all())
            audit = db.query(AgentResolverTeamMappingAuditRecord).one()
            self.assertEqual(groups, ["APPLICATION_OPERATIONS", "IDENTITY_ACCESS"])
            self.assertEqual(json.loads(audit.previous_groups), [])
            self.assertEqual(json.loads(audit.new_groups), groups)

        inactive = self.client.put("/admin/agent-team-mappings/inactive", json={
            "resolver_groups": ["SOFTWARE_ENGINEERING"],
            "expected_resolver_groups": [],
        })
        self.assertEqual(inactive.status_code, 409)

    def test_directory_people_flags_and_remote_requester_membership(self):
        self._as_role("admin")
        disabled = self.client.get("/admin/directory-people")
        self.assertEqual(disabled.status_code, 404)

        with self.session_factory() as db:
            db.add(ExternalUserRecord(
                id="remote-requester",
                binding_id="binding-one",
                provider="freshservice",
                external_id="requester-100",
                user_type="requester",
                name="Remote Requester",
                email="requester@example.com",
                active=True,
                profile_json="{}",
                fetched_at=datetime.utcnow(),
            ))
            directory_service.ensure_directory_projection(db)
            db.commit()

        flags = {
            "DIRECTORY_PEOPLE_READ_ENABLED": "true",
            "DIRECTORY_PEOPLE_WRITE_ENABLED": "true",
            "REMOTE_REQUESTER_TEAM_ELIGIBLE": "true",
        }
        with patch.dict(os.environ, flags):
            listed = self.client.get(
                "/admin/directory-people", params={"source_type": "requester"}
            )
            self.assertEqual(listed.status_code, 200, listed.text)
            requester = listed.json()["items"][0]
            self.assertIsNone(requester["user_id"])
            self.assertIsNone(requester["role"])
            self.assertEqual(requester["source_types"], ["freshservice_requester"])

            updated = self.client.put(
                f"/admin/directory-people/{requester['id']}/resolver-groups",
                json={
                    "resolver_groups": ["SERVICE_DESK"],
                    "expected_resolver_groups": [],
                    "expected_version": requester["version"],
                },
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(
                updated.json()["resolver_groups"], ["SERVICE_DESK"]
            )

            self._as_role("supervisor")
            forbidden = self.client.put(
                f"/admin/directory-people/{requester['id']}/resolver-groups",
                json={
                    "resolver_groups": [],
                    "expected_resolver_groups": ["SERVICE_DESK"],
                    "expected_version": updated.json()["version"],
                },
            )
            self.assertEqual(forbidden.status_code, 403)

    def test_admin_and_supervisor_manage_only_structured_versioned_rules(self):
        payload = {
            "name": "Business application transactions",
            "description": "Functional transaction behavior remains with the BA team.",
            "enabled": True,
            "priority": 20,
            "scope": None,
            "service_contains": "Billing platform",
            "failure_domain_contains": "business process",
            "primary_group": "IDENTITY_ACCESS",
            "secondary_group": None,
        }
        self._as_role("supervisor")
        with self.session_factory() as db:
            db.add(TicketRecord(
                id="routed-ticket",
                subject="Existing routed ticket",
                description="Existing evidence",
                reporter="requester@example.invalid",
                ai_routing_input_hash="old-route-hash",
            ))
            db.add(AIArtifactRecord(
                ticket_id="routed-ticket",
                artifact="route",
                input_hash="old-route-hash",
                pipeline_version="old-policy",
                provider="test",
                model="test",
                synthetic=False,
                content_hash="old-content",
                active=True,
            ))
            db.commit()
        created = self.client.post("/admin/routing-rules", json=payload)
        self.assertEqual(created.status_code, 201)
        rule = created.json()
        self.assertEqual(rule["version"], 1)

        invalid = self.client.post("/admin/routing-rules", json={
            **payload,
            "name": "Unconditional",
            "service_contains": None,
            "failure_domain_contains": None,
        })
        self.assertEqual(invalid.status_code, 422)

        updated = self.client.put(f"/admin/routing-rules/{rule['id']}", json={
            **payload,
            "enabled": False,
            "expected_version": 1,
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["version"], 2)
        self.assertFalse(updated.json()["enabled"])
        stale = self.client.put(f"/admin/routing-rules/{rule['id']}", json={
            **payload,
            "expected_version": 1,
        })
        self.assertEqual(stale.status_code, 409)

        with self.session_factory() as db:
            self.assertEqual(db.query(RoutingRuleAuditRecord).count(), 2)
            self.assertEqual(routing_rules.active_rule_payloads(db), [])
            artifact = db.query(AIArtifactRecord).one()
            ticket = db.get(TicketRecord, "routed-ticket")
            self.assertFalse(artifact.active)
            self.assertIsNone(ticket.ai_routing_input_hash)


class RoutingRulePromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_structured_rule_fields_reach_the_ai_input(self):
        class CapturingLLM:
            def __init__(self):
                self.prompt = None

            async def analyze(self, prompt, **_kwargs):
                self.prompt = json.loads(prompt)
                return {
                    "primary_group": "IDENTITY_ACCESS",
                    "secondary_group": None,
                    "confidence": 0.82,
                    "scope": "single_user",
                    "affected_service": "Billing platform",
                    "failure_domain": "business process",
                    "reason": "The functional transaction behavior is directly observed.",
                }

        llm = CapturingLLM()
        result = await IntelligenceEngine(llm).route_ticket(
            {"subject": "Transaction issue", "description": "Incorrect business behavior"},
            organization_routing_rules=[{
                "priority": 20,
                "when": {"service_contains": "Billing platform"},
                "recommend": {"primary_group": "IDENTITY_ACCESS", "secondary_group": None},
            }],
        )
        self.assertEqual(result["primary_group"], "IDENTITY_ACCESS")
        self.assertEqual(llm.prompt["organization_routing_rules"][0]["priority"], 20)
        self.assertNotIn("name", llm.prompt["organization_routing_rules"][0])

    async def test_semantic_provider_draft_is_conservatively_normalized(self):
        class SemanticallyInvalidLLM:
            async def analyze(self, _prompt, **_kwargs):
                return {
                    "primary_group": "IDENTITY_ACCESS",
                    "secondary_group": "SERVICE_DESK",
                    "confidence": 0.82,
                    "scope": "single_user",
                    "affected_service": "unknown",
                    "failure_domain": "business process",
                    "reason": "The business transaction is directly described.",
                }

        result = await IntelligenceEngine(SemanticallyInvalidLLM()).route_ticket(
            {"subject": "Order field issue", "description": "A field is missing."}
        )

        self.assertEqual(result["primary_group"], "IDENTITY_ACCESS")
        self.assertIsNone(result["secondary_group"])
        self.assertEqual(result["confidence"], 0.59)

if __name__ == "__main__":
    unittest.main()
