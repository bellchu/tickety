import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    TicketCategoryRecord,
    TicketRecord,
    UserRecord,
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
                TicketRecord(
                    id="ticket-1",
                    subject="Production incident",
                    recommended_solution="stale generated guidance",
                    ai_status="complete",
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
        self.assertEqual({user["id"] for user in response.json()}, {"admin", "supervisor", "agent"})

    def test_agent_cannot_bulk_update_tickets(self):
        self._as_role("agent")

        response = self.client.post(
            "/tickets/bulk",
            json={"ticket_ids": ["ticket-1"], "action": "close"},
        )

        self.assertEqual(response.status_code, 403)
        with self.session_factory() as db:
            self.assertNotEqual(db.get(TicketRecord, "ticket-1").status, "Closed")

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


if __name__ == "__main__":
    unittest.main()
