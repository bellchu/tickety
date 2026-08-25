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
    ExternalGroupMembershipRecord,
    ExternalGroupRecord,
    ExternalUserRecord,
    TicketRecord,
    UserExternalIdentityLinkRecord,
    UserRecord,
    get_db,
)


class AgentWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        now = datetime.utcnow()
        with self.session_factory() as db:
            agent = UserRecord(
                id="agent-local",
                name="Alice Agent",
                email="alice@example.com",
                role="agent",
                is_active=True,
            )
            admin = UserRecord(
                id="admin-local",
                name="Admin User",
                email="admin@example.com",
                role="admin",
                is_active=True,
            )
            external_agent = ExternalUserRecord(
                id="external-alice",
                binding_id="binding-one",
                provider="freshservice",
                external_id="1001",
                user_type="agent",
                name="Alice Provider",
                email="alice@example.com",
                active=True,
                profile_json="{}",
                fetched_at=now,
            )
            external_other = ExternalUserRecord(
                id="external-bob",
                binding_id="binding-one",
                provider="freshservice",
                external_id="1002",
                user_type="agent",
                name="Bob Provider",
                email="bob@example.com",
                active=True,
                profile_json="{}",
                fetched_at=now,
            )
            service_desk = ExternalGroupRecord(
                id="group-service-desk",
                binding_id="binding-one",
                provider="freshservice",
                external_id="2001",
                name="Service Desk",
                active=True,
                profile_json="{}",
                fetched_at=now,
            )
            other_group = ExternalGroupRecord(
                id="group-other",
                binding_id="binding-one",
                provider="freshservice",
                external_id="2002",
                name="Other Team",
                active=True,
                profile_json="{}",
                fetched_at=now,
            )
            db.add_all([agent, admin, external_agent, external_other, service_desk, other_group])
            db.flush()
            db.add_all([
                ExternalGroupMembershipRecord(
                    external_group_id=service_desk.id,
                    external_user_id=external_agent.id,
                    membership_kind="member",
                ),
                ExternalGroupMembershipRecord(
                    external_group_id=other_group.id,
                    external_user_id=external_agent.id,
                    membership_kind="observer",
                ),
            ])
            # Deliberately omit the identity link initially. Matching email
            # addresses must never grant provider ticket access implicitly.
            db.add_all([
                self._ticket(
                    "local-mine",
                    "Locally assigned work",
                    now,
                    assignee_id=agent.id,
                    response_due_at=now + timedelta(minutes=30),
                ),
                self._ticket(
                    "provider-mine",
                    "Provider personal assignment",
                    now - timedelta(hours=1),
                    external_assignee_id=external_agent.external_id,
                ),
                self._ticket(
                    "team-assigned",
                    "Team ticket assigned to Bob",
                    now - timedelta(hours=2),
                    external_assignee_id=external_other.external_id,
                    external_group_id=service_desk.external_id,
                ),
                self._ticket(
                    "team-unassigned",
                    "Unassigned team ticket",
                    now - timedelta(hours=3),
                    external_group_id=service_desk.external_id,
                ),
                self._ticket(
                    "outside-scope",
                    "Ticket in another group",
                    now - timedelta(hours=4),
                    external_group_id=other_group.external_id,
                ),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        self.current_user = UserRecord(
            id="agent-local",
            name="Alice Agent",
            email="alice@example.com",
            role="agent",
            is_active=True,
        )
        main.app.dependency_overrides[get_db] = override_db
        main.app.dependency_overrides[main.get_current_user] = lambda: self.current_user
        main.app.dependency_overrides[main.get_authenticated_user] = lambda: self.current_user
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.roles_patch = patch.object(main, "_roles_required_for_request", return_value=None)
        self.roles_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.auth_patch.stop()
        self.roles_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    @staticmethod
    def _ticket(ticket_id, subject, created_at, **values):
        return TicketRecord(
            id=ticket_id,
            subject=subject,
            description=f"Description for {subject}",
            reporter="requester@example.com",
            status="Open",
            priority="P2",
            binding_id="binding-one",
            external_source="freshservice",
            external_id=ticket_id,
            external_created_at=created_at,
            created_at=created_at,
            updated_at=created_at,
            **values,
        )

    def _link_external_identity(self):
        with self.session_factory() as db:
            db.add(UserExternalIdentityLinkRecord(
                user_id="agent-local",
                external_user_id="external-alice",
                binding_id="binding-one",
                provider="freshservice",
                created_by="admin-local",
            ))
            db.commit()

    def test_identity_is_explicit_and_never_guessed_from_email(self):
        before = self.client.get("/agent-workspace/tickets", params={"scope": "mine"})
        self.assertEqual(before.status_code, 200)
        self.assertEqual({item["id"] for item in before.json()}, {"local-mine"})
        self.assertIsNone(self.client.get("/agent-workspace/bootstrap").json()["identity"])

        self._link_external_identity()
        after = self.client.get("/agent-workspace/tickets", params={"scope": "mine"})
        self.assertEqual(
            {item["id"] for item in after.json()},
            {"local-mine", "provider-mine"},
        )

    def test_personal_and_authoritative_team_inboxes_are_separate(self):
        self._link_external_identity()
        bootstrap = self.client.get("/agent-workspace/bootstrap")
        self.assertEqual(bootstrap.status_code, 200)
        payload = bootstrap.json()
        self.assertEqual(payload["identity"]["external_id"], "1001")
        self.assertEqual([team["name"] for team in payload["teams"]], ["Service Desk"])
        self.assertEqual(payload["teams"][0]["ticket_count"], 2)
        self.assertEqual(payload["teams"][0]["unassigned_count"], 1)
        self.assertEqual(payload["counts"]["inbox"], 2)

        team = self.client.get("/agent-workspace/tickets", params={
            "scope": "team",
            "team_id": "group-service-desk",
        })
        self.assertEqual(team.status_code, 200)
        self.assertEqual(
            {item["id"] for item in team.json()},
            {"team-assigned", "team-unassigned"},
        )
        self.assertTrue(all(item["assignment_scope"] == "team" for item in team.json()))

        unassigned = self.client.get("/agent-workspace/tickets", params={
            "scope": "team",
            "team_id": "group-service-desk",
            "folder": "unassigned",
        })
        self.assertEqual([item["id"] for item in unassigned.json()], ["team-unassigned"])

    def test_mailbox_state_supports_unread_star_and_follow_up(self):
        self._link_external_identity()
        initial = self.client.get("/agent-workspace/tickets", params={"scope": "mine"}).json()
        target = next(item for item in initial if item["id"] == "provider-mine")
        self.assertTrue(target["is_unread"])
        self.assertTrue(target["needs_reply"])

        follow_up = datetime.utcnow() - timedelta(minutes=1)
        changed = self.client.put("/agent-workspace/tickets/provider-mine/state", json={
            "mark_seen": True,
            "starred": True,
            "follow_up_at": follow_up.isoformat(),
        })
        self.assertEqual(changed.status_code, 200)

        starred = self.client.get("/agent-workspace/tickets", params={
            "scope": "mine",
            "folder": "starred",
        }).json()
        self.assertEqual([item["id"] for item in starred], ["provider-mine"])
        self.assertFalse(starred[0]["is_unread"])
        self.assertTrue(starred[0]["is_starred"])
        self.assertIsNotNone(starred[0]["follow_up_at"])

        due = self.client.get("/agent-workspace/tickets", params={
            "scope": "mine",
            "folder": "follow_up",
        }).json()
        self.assertEqual([item["id"] for item in due], ["provider-mine"])

    def test_all_tickets_remains_a_complete_browsable_directory_for_agents(self):
        response = self.client.get("/tickets", params={"limit": 100})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 5)
        detail = self.client.get("/tickets/outside-scope")
        self.assertEqual(detail.status_code, 200)

    def test_admin_can_create_and_audit_an_explicit_identity_link(self):
        self.current_user = UserRecord(
            id="admin-local",
            name="Admin User",
            email="admin@example.com",
            role="admin",
            is_active=True,
        )
        response = self.client.put("/admin/agent-identity-links/agent-local", json={
            "external_user_id": "external-alice",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["external_id"], "1001")
        links = self.client.get("/admin/agent-identity-links").json()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["user_id"], "agent-local")


if __name__ == "__main__":
    unittest.main()
