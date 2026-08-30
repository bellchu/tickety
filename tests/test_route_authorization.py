import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    ChangeApprovalRecord,
    ChangeRecord,
    ExternalUserRecord,
    ExternalAttachmentRecord,
    ExternalConversationRecord,
    RecognitionRecord,
    SessionRecord,
    TicketCategoryRecord,
    TicketRecord,
    UserRecord,
    UserExternalIdentityLinkRecord,
    get_db,
)


class RouteAuthorizationTests(unittest.TestCase):
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
                UserRecord(id="auditor", name="Unknown Role", role="auditor", is_active=True),
                UserRecord(id="inactive", name="Inactive", role="agent", is_active=False),
                TicketRecord(
                    id="ticket-1",
                    subject="Production incident",
                    recommended_solution="stale generated guidance",
                    ai_status="complete",
                    assignee_id="inactive",
                ),
                TicketCategoryRecord(name="Network"),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.auth_middleware_patch = patch.object(
            main,
            "_auth_required_for_request",
            return_value=False,
        )
        self.auth_middleware_patch.start()
        # These tests exercise endpoint dependencies with explicit user
        # overrides. Privileged-route middleware now independently requires a
        # cookie-backed session in demo mode, so bypass only that duplicate
        # middleware role check in this focused dependency contract suite.
        self.roles_policy = main._roles_required_for_request
        self.middleware_roles_patch = patch.object(
            main,
            "_roles_required_for_request",
            return_value=None,
        )
        self.middleware_roles_patch.start()
        self.demo_ticketing_patch = patch.object(
            main.settings_module,
            "is_production_mode",
            return_value=False,
        )
        self.demo_ticketing_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.demo_ticketing_patch.stop()
        self.middleware_roles_patch.stop()
        self.auth_middleware_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _as_role(self, role):
        def current_user():
            with self.session_factory() as db:
                return db.get(UserRecord, role)

        main.app.dependency_overrides[main.get_current_user] = current_user
        main.app.dependency_overrides[main.get_authenticated_user] = current_user
        main.app.dependency_overrides[main.get_protected_ai_user] = current_user

    def test_agent_cannot_permanently_delete_ticket(self):
        self._as_role("agent")

        response = self.client.delete("/tickets/ticket-1")

        self.assertEqual(response.status_code, 403)
        with self.session_factory() as db:
            self.assertIsNotNone(db.get(TicketRecord, "ticket-1"))

    def test_supervisor_can_permanently_delete_ticket(self):
        self._as_role("supervisor")

        with patch.object(main.ticket_vectors, "delete_ticket_documents"):
            response = self.client.delete("/tickets/ticket-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "deleted", "ticket_id": "ticket-1"})
        with self.session_factory() as db:
            self.assertIsNone(db.get(TicketRecord, "ticket-1"))

    def test_agent_cannot_list_users(self):
        self._as_role("agent")

        response = self.client.get("/users")

        self.assertEqual(response.status_code, 403)

    def test_supervisor_can_list_users_with_existing_contract(self):
        self._as_role("supervisor")

        response = self.client.get("/users")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {user["id"] for user in response.json()},
            {"admin", "supervisor", "agent", "auditor", "inactive"},
        )

    def test_user_directory_is_bounded_filterable_and_reports_role_coverage(self):
        self._as_role("supervisor")
        with self.session_factory() as db:
            db.add_all([
                UserRecord(
                    id=f"extra-{index:03d}",
                    name=f"Extra Agent {index:03d}",
                    role="agent",
                    is_active=True,
                )
                for index in range(105)
            ])
            db.add(UserRecord(
                id="literal-wildcard-user",
                name="Literal 100%_coverage",
                role="agent",
                is_active=True,
            ))
            db.commit()

        bounded = self.client.get("/users")
        self.assertEqual(bounded.status_code, 200, bounded.text)
        self.assertEqual(len(bounded.json()), 100)
        self.assertEqual(bounded.headers["x-page-limit"], "100")
        self.assertEqual(bounded.headers["x-page-offset"], "0")
        self.assertEqual(bounded.headers["x-has-more"], "true")

        filtered = self.client.get(
            "/users",
            params={
                "search": "100%_coverage",
                "is_active": "true",
                "limit": 10,
                "include_summary": "true",
            },
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(
            [user["id"] for user in filtered.json()],
            ["literal-wildcard-user"],
        )
        self.assertEqual(filtered.headers["x-has-more"], "false")
        self.assertEqual(filtered.headers["x-active-admin-count"], "1")
        self.assertEqual(filtered.headers["x-active-supervisor-count"], "1")
        self.assertEqual(filtered.headers["x-active-agent-count"], "107")
        self.assertEqual(filtered.headers["x-active-other-count"], "1")

    def test_identity_link_directory_is_bounded_and_batches_visible_users(self):
        self._as_role("admin")
        with self.session_factory() as db:
            db.add_all([
                ExternalUserRecord(
                    id="external-agent",
                    binding_id="binding",
                    provider="freshservice",
                    external_id="agent-1",
                    name="Agent External",
                ),
                ExternalUserRecord(
                    id="external-supervisor",
                    binding_id="binding",
                    provider="freshservice",
                    external_id="supervisor-1",
                    name="Supervisor External",
                ),
            ])
            db.flush()
            db.add_all([
                UserExternalIdentityLinkRecord(
                    user_id="agent",
                    external_user_id="external-agent",
                    binding_id="binding",
                    provider="freshservice",
                    created_by="admin",
                ),
                UserExternalIdentityLinkRecord(
                    user_id="supervisor",
                    external_user_id="external-supervisor",
                    binding_id="binding",
                    provider="freshservice",
                    created_by="admin",
                ),
            ])
            db.commit()

        bounded = self.client.get(
            "/admin/agent-identity-links", params={"limit": 1}
        )
        self.assertEqual(bounded.status_code, 200, bounded.text)
        self.assertEqual(len(bounded.json()), 1)
        self.assertEqual(bounded.headers["x-has-more"], "true")

        batched = self.client.get(
            "/admin/agent-identity-links",
            params=[
                ("user_id", "agent"),
                ("user_id", "supervisor"),
                ("limit", "10"),
            ],
        )
        self.assertEqual(batched.status_code, 200, batched.text)
        self.assertEqual(
            {item["user_id"] for item in batched.json()},
            {"agent", "supervisor"},
        )
        self.assertEqual(batched.headers["x-has-more"], "false")

    def test_attachment_page_filters_private_conversations_before_bounding(self):
        self._as_role("agent")
        with self.session_factory() as db:
            db.add(ExternalConversationRecord(
                id="private-conversation",
                binding_id="binding",
                provider="freshservice",
                ticket_id="ticket-1",
                provider_ticket_id="provider-ticket-1",
                external_id="private-reply",
                body_hash="private-body-hash",
                is_private=True,
                revision_hash="private-revision-hash",
            ))
            db.add_all([
                ExternalAttachmentRecord(
                    id="attachment-private",
                    binding_id="binding",
                    provider="freshservice",
                    ticket_id="ticket-1",
                    provider_ticket_id="provider-ticket-1",
                    owner_type="conversation",
                    owner_external_id="private-reply",
                    external_id="private-file",
                    file_name="private.txt",
                    storage_status="stored",
                    created_at=datetime(2026, 1, 1),
                ),
                ExternalAttachmentRecord(
                    id="attachment-public-1",
                    binding_id="binding",
                    provider="freshservice",
                    ticket_id="ticket-1",
                    provider_ticket_id="provider-ticket-1",
                    owner_type="ticket",
                    owner_external_id="provider-ticket-1",
                    external_id="public-file-1",
                    file_name="public-1.txt",
                    storage_status="stored",
                    created_at=datetime(2026, 1, 2),
                ),
                ExternalAttachmentRecord(
                    id="attachment-public-2",
                    binding_id="binding",
                    provider="freshservice",
                    ticket_id="ticket-1",
                    provider_ticket_id="provider-ticket-1",
                    owner_type="ticket",
                    owner_external_id="provider-ticket-1",
                    external_id="public-file-2",
                    file_name="public-2.txt",
                    storage_status="stored",
                    created_at=datetime(2026, 1, 3),
                ),
            ])
            db.commit()

        response = self.client.get(
            "/tickets/ticket-1/attachments", params={"limit": 1}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [attachment["id"] for attachment in response.json()],
            ["attachment-public-1"],
        )
        self.assertEqual(response.headers["x-page-limit"], "1")
        self.assertEqual(response.headers["x-page-offset"], "0")
        self.assertEqual(response.headers["x-has-more"], "true")

    def test_only_admin_can_purge_a_deactivated_user(self):
        with self.session_factory() as db:
            db.add_all([
                SessionRecord(token="inactive-session", user_id="inactive"),
                RecognitionRecord(user_id="inactive", recognition_key="inactive-award"),
                ChangeRecord(
                    id="approved-change",
                    title="Completed CAB review",
                    status="Approved",
                    requested_by="agent",
                ),
                ChangeRecord(
                    id="pending-change",
                    title="Awaiting CAB review",
                    status="CAB Review",
                    requested_by="agent",
                ),
            ])
            db.flush()
            db.add_all([
                ChangeApprovalRecord(
                    change_id="approved-change",
                    approver_id="inactive",
                    decision="approved",
                ),
                ChangeApprovalRecord(
                    change_id="pending-change",
                    approver_id="inactive",
                ),
            ])
            db.commit()

        self._as_role("supervisor")
        response = self.client.delete("/users/inactive/purge")
        self.assertEqual(response.status_code, 403)

        self._as_role("admin")
        response = self.client.delete("/users/inactive/purge")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "purged")
        self.assertEqual(response.json()["removed_pending_approvals"], 1)
        self.assertEqual(response.json()["anonymized_decided_approvals"], 1)
        with self.session_factory() as db:
            self.assertIsNone(db.get(UserRecord, "inactive"))
            self.assertIsNone(db.get(SessionRecord, "inactive-session"))
            self.assertEqual(
                db.query(RecognitionRecord).filter(RecognitionRecord.user_id == "inactive").count(),
                0,
            )
            self.assertIsNotNone(db.get(TicketRecord, "ticket-1"))
            self.assertIsNone(db.get(TicketRecord, "ticket-1").assignee_id)
            decided = db.query(ChangeApprovalRecord).filter(
                ChangeApprovalRecord.change_id == "approved-change"
            ).one()
            self.assertIsNone(decided.approver_id)
            self.assertEqual(decided.decision, "approved")
            self.assertEqual(db.get(ChangeRecord, "approved-change").status, "Approved")
            self.assertEqual(
                db.query(ChangeApprovalRecord).filter(
                    ChangeApprovalRecord.change_id == "pending-change"
                ).count(),
                0,
            )
            self.assertEqual(db.get(ChangeRecord, "pending-change").status, "CAB Review")

    def test_active_user_must_be_deactivated_before_purge(self):
        self._as_role("admin")
        response = self.client.delete("/users/agent/purge")
        self.assertEqual(response.status_code, 409)
        with self.session_factory() as db:
            self.assertIsNotNone(db.get(UserRecord, "agent"))

    def test_last_active_admin_cannot_be_deactivated(self):
        self._as_role("admin")

        patched = self.client.patch("/users/admin", json={"is_active": False})
        deleted = self.client.delete("/users/admin")

        self.assertEqual(patched.status_code, 400, patched.text)
        self.assertEqual(deleted.status_code, 400, deleted.text)
        self.assertEqual(
            patched.json(),
            {"detail": "Cannot deactivate the last active admin"},
        )
        with self.session_factory() as db:
            self.assertTrue(db.get(UserRecord, "admin").is_active)

    def test_stale_admin_request_cannot_demote_the_only_active_admin(self):
        # This models the second half of a concurrent cross-admin mutation:
        # authorization completed while the actor was active, but the first
        # serialized transaction has since removed that actor from the active
        # admin set.
        stale_actor = UserRecord(
            id="stale-admin",
            name="Stale Admin",
            role="admin",
            is_active=True,
        )
        main.app.dependency_overrides[main.get_current_user] = lambda: stale_actor
        main.app.dependency_overrides[main.get_authenticated_user] = lambda: stale_actor

        response = self.client.patch("/users/admin", json={"role": "agent"})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            response.json(),
            {"detail": "Cannot deactivate the last active admin"},
        )
        with self.session_factory() as db:
            self.assertEqual(db.get(UserRecord, "admin").role, "admin")

    def test_canonical_email_identity_is_unique_across_user_writes(self):
        self._as_role("supervisor")

        created = self.client.post("/users", json={
            "name": "First Account",
            "email": " Shared@Example.COM ",
            "role": "agent",
        })
        duplicate = self.client.post("/users", json={
            "name": "Second Account",
            "email": "shared@example.com",
            "role": "agent",
        })
        conflicting_update = self.client.patch(
            "/users/agent",
            json={"email": "SHARED@example.com"},
        )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["email"], "shared@example.com")
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(conflicting_update.status_code, 409, conflicting_update.text)

    def test_agent_cannot_bulk_update_tickets(self):
        self._as_role("agent")

        response = self.client.post(
            "/tickets/bulk",
            json={"ticket_ids": ["ticket-1"], "action": "close"},
        )

        self.assertEqual(response.status_code, 403)
        with self.session_factory() as db:
            self.assertNotEqual(db.get(TicketRecord, "ticket-1").status, "Closed")

    def test_agent_can_read_ticket_option_config(self):
        self._as_role("agent")

        statuses = self.client.get("/config/statuses")
        priorities = self.client.get("/config/priorities")

        self.assertEqual(statuses.status_code, 200)
        self.assertEqual(priorities.status_code, 200)

    def test_unknown_active_role_cannot_read_operational_collections(self):
        self._as_role("auditor")

        for path in (
            "/projects",
            "/services",
            "/service-requests",
            "/problems",
            "/problems/missing",
            "/assets",
            "/assets/stats",
            "/assets/missing",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 403, response.text)

    def test_recognitions_are_self_scoped_for_agents(self):
        self._as_role("agent")

        own = self.client.get("/recognitions/agent")
        another_user = self.client.get("/recognitions/admin")

        self.assertEqual(own.status_code, 200)
        self.assertEqual(another_user.status_code, 403)

    def test_leaderboard_excludes_inactive_users(self):
        self._as_role("agent")

        response = self.client.get("/leaderboard")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("inactive", {row["id"] for row in response.json()})

    def test_supervisor_bulk_update_validates_references(self):
        self._as_role("supervisor")

        response = self.client.post(
            "/tickets/bulk",
            json={"ticket_ids": ["ticket-1"], "action": "assign", "value": "missing"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Assignee is not an active user")

    def test_supervisor_can_bulk_update_with_audit_contract(self):
        self._as_role("supervisor")

        response = self.client.post(
            "/tickets/bulk",
            json={"ticket_ids": ["ticket-1"], "action": "set_category", "value": "Network"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 1)
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "ticket-1")
            self.assertEqual(ticket.category, "Network")
            self.assertIsNone(ticket.recommended_solution)
            self.assertEqual(ticket.ai_status, "partial")

    def test_bulk_close_cancels_pending_ai_work(self):
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "ticket-1")
            ticket.ai_status = "queued"
            ticket.ai_claim_id = "stale-claim"
            ticket.ai_lease_expires_at = datetime.utcnow() + timedelta(minutes=5)
            ticket.ai_next_attempt_at = datetime.utcnow() + timedelta(minutes=10)
            ticket.ai_requested_artifacts = "triage,summary"
            ticket.ai_error = "summary:timeout"
            db.commit()

        self._as_role("supervisor")
        response = self.client.post(
            "/tickets/bulk",
            json={"ticket_ids": ["ticket-1"], "action": "close"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "ticket-1")
            self.assertEqual(ticket.status, "Closed")
            self.assertEqual(ticket.ai_status, "not_applicable")
            self.assertEqual(ticket.ai_error, "terminal_ticket")
            self.assertIsNone(ticket.ai_claim_id)
            self.assertIsNone(ticket.ai_lease_expires_at)
            self.assertIsNone(ticket.ai_next_attempt_at)
            self.assertIsNone(ticket.ai_requested_artifacts)

    def test_middleware_policy_matches_route_policy(self):
        self.assertEqual(
            self.roles_policy("/tickets/ticket-1", "DELETE"),
            {"admin", "supervisor"},
        )
        self.assertEqual(
            self.roles_policy("/users", "GET"),
            {"admin", "supervisor"},
        )
        self.assertEqual(
            self.roles_policy("/tickets/bulk", "POST"),
            {"admin", "supervisor"},
        )
        self.assertEqual(
            self.roles_policy("/service-requests/request-1/approval", "PATCH"),
            {"admin", "supervisor"},
        )
        self.assertEqual(
            self.roles_policy("/email/send", "POST"),
            {"admin", "supervisor", "agent"},
        )
        self.assertIsNone(self.roles_policy("/config/statuses", "GET"))
        self.assertIsNone(self.roles_policy("/config/priorities", "GET"))
        self.assertEqual(
            self.roles_policy("/config/statuses", "POST"),
            {"admin", "supervisor"},
        )
        self.assertEqual(
            self.roles_policy("/config/notifications", "GET"),
            {"admin", "supervisor"},
        )


if __name__ == "__main__":
    unittest.main()
