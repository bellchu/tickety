import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import agent_workspace, main
from app.backend.database import (
    Base,
    ExternalConversationRecord,
    ExternalGroupMembershipRecord,
    ExternalGroupRecord,
    ExternalUserRecord,
    ProblemRecord,
    ProblemTicketLinkRecord,
    TicketPriorityConfigRecord,
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

    def test_exact_ticket_filter_restores_a_deep_link_without_widening_scope(self):
        self._link_external_identity()

        selected = self.client.get(
            "/agent-workspace/tickets",
            params={
                "scope": "mine",
                "ticket_id": "provider-mine",
                "limit": 1,
            },
        )
        outside = self.client.get(
            "/agent-workspace/tickets",
            params={"scope": "mine", "ticket_id": "outside-scope"},
        )

        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual([item["id"] for item in selected.json()], ["provider-mine"])
        self.assertEqual(selected.headers["x-has-more"], "false")
        self.assertEqual(outside.status_code, 200, outside.text)
        self.assertEqual(outside.json(), [])

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

    def test_configured_priority_weight_drives_focus_order_and_score(self):
        now = datetime.utcnow()
        with self.session_factory() as db:
            db.add(TicketPriorityConfigRecord(
                name="Sev Zero",
                label="Severity zero",
                color="red",
                weight=1,
                sort_order=99,
            ))
            custom_priority_ticket = self._ticket(
                "custom-critical-mine",
                "Custom critical priority",
                now,
                assignee_id="agent-local",
            )
            custom_priority_ticket.priority = "sev zero"
            standard_priority_ticket = self._ticket(
                "standard-high-mine",
                "Standard high priority",
                now,
                assignee_id="agent-local",
            )
            nonportable_priority_ticket = self._ticket(
                "nonportable-priority-mine",
                "Provider priority with a tab suffix",
                now,
                assignee_id="agent-local",
            )
            nonportable_priority_ticket.priority = "sev zero\t"
            db.add_all([
                custom_priority_ticket,
                standard_priority_ticket,
                nonportable_priority_ticket,
            ])
            db.commit()

        response = self.client.get(
            "/agent-workspace/tickets",
            params={"scope": "mine", "limit": 100},
        )

        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()
        positions = {item["id"]: index for index, item in enumerate(items)}
        by_id = {item["id"]: item for item in items}
        self.assertLess(
            positions["custom-critical-mine"],
            positions["standard-high-mine"],
        )
        self.assertEqual(
            by_id["custom-critical-mine"]["next_best_score"],
            by_id["standard-high-mine"]["next_best_score"] + 16,
        )
        self.assertLess(
            positions["standard-high-mine"],
            positions["nonportable-priority-mine"],
        )
        self.assertEqual(
            by_id["nonportable-priority-mine"]["next_best_score"],
            by_id["standard-high-mine"]["next_best_score"] - 20,
        )

    def test_all_tickets_remains_a_complete_browsable_directory_for_agents(self):
        response = self.client.get("/tickets", params={"limit": 100})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 5)
        detail = self.client.get("/tickets/outside-scope")
        self.assertEqual(detail.status_code, 200)

    def test_sla_risk_excludes_paused_and_on_hold_assignments(self):
        now = datetime.utcnow()
        with self.session_factory() as db:
            db.add_all([
                self._ticket(
                    "paused-mine",
                    "Paused assigned work",
                    now - timedelta(hours=8),
                    assignee_id="agent-local",
                    workflow_status="Paused",
                    response_due_at=now - timedelta(hours=2),
                ),
                self._ticket(
                    "on-hold-mine",
                    "On-hold assigned work",
                    now - timedelta(hours=8),
                    assignee_id="agent-local",
                    external_status="On Hold",
                    response_due_at=now - timedelta(hours=2),
                ),
                self._ticket(
                    "explicitly-paused-mine",
                    "Explicitly paused assigned work",
                    now - timedelta(hours=8),
                    assignee_id="agent-local",
                    response_due_at=now - timedelta(hours=2),
                    sla_paused_at=now - timedelta(hours=3),
                ),
            ])
            db.commit()

        bootstrap = self.client.get("/agent-workspace/bootstrap")
        sla_folder = self.client.get(
            "/agent-workspace/tickets",
            params={"scope": "mine", "folder": "sla_at_risk"},
        )
        inbox = self.client.get(
            "/agent-workspace/tickets",
            params={"scope": "mine", "folder": "inbox"},
        )

        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        self.assertEqual(bootstrap.json()["counts"]["sla_at_risk"], 1)
        self.assertEqual([item["id"] for item in sla_folder.json()], ["local-mine"])
        exempt_ids = {
            "paused-mine",
            "on-hold-mine",
            "explicitly-paused-mine",
        }
        exempt_rows = [item for item in inbox.json() if item["id"] in exempt_ids]
        self.assertEqual({item["id"] for item in exempt_rows}, exempt_ids)
        for item in exempt_rows:
            self.assertFalse(item["sla_at_risk"])
            self.assertNotIn("SLA is overdue", item["next_best_reasons"])

    def test_large_team_directory_is_bounded_and_aggregated_in_constant_queries(self):
        self._link_external_identity()
        scale_group_count = agent_workspace.MAX_ACCESSIBLE_GROUPS + 5
        now = datetime.utcnow()
        with self.session_factory() as db:
            groups = [
                ExternalGroupRecord(
                    id=f"scale-group-{index:03d}",
                    binding_id="binding-one",
                    provider="freshservice",
                    external_id=f"scale-external-{index:03d}",
                    name=f"Scale Team {index:03d}",
                    active=True,
                    profile_json="{}",
                    fetched_at=now,
                )
                for index in range(scale_group_count)
            ]
            db.add_all(groups)
            db.flush()
            db.add_all([
                ExternalGroupMembershipRecord(
                    external_group_id=group.id,
                    external_user_id="external-alice",
                    membership_kind="member",
                )
                for group in groups
            ])
            scale_tickets = [
                self._ticket(
                    f"scale-ticket-{index:03d}",
                    f"Scale team ticket {index:03d}",
                    now - timedelta(minutes=index),
                    external_group_id=group.external_id,
                )
                for index, group in enumerate(groups)
            ]
            target_ticket = scale_tickets[-1]
            target_ticket.ai_reasoning = "Deep team reasoning"
            target_ticket.suggested_response = "Deep team response"
            target_ticket.summary = "Deep team summary"
            db.add_all(scale_tickets)
            db.add(ProblemRecord(
                id="scale-problem",
                title="Scale problem",
                assigned_to="agent-local",
            ))
            db.flush()
            db.add(ProblemTicketLinkRecord(
                problem_id="scale-problem",
                ticket_id=target_ticket.id,
            ))
            db.commit()

        selects = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(" ".join(statement.lower().split()))

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            bootstrap = self.client.get("/agent-workspace/bootstrap")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        payload = bootstrap.json()
        self.assertEqual(
            len(payload["teams"]),
            agent_workspace.MAX_ACCESSIBLE_GROUPS,
        )
        self.assertTrue(payload["teams_truncated"])
        self.assertEqual(bootstrap.headers["x-teams-limit"], "100")
        self.assertEqual(bootstrap.headers["x-teams-truncated"], "true")
        self.assertEqual(payload["counts"]["team_inbox"], scale_group_count + 2)
        self.assertEqual(payload["counts"]["team_unassigned"], scale_group_count + 1)
        self.assertTrue(all(team["ticket_count"] == 1 for team in payload["teams"]))
        self.assertTrue(all(team["unassigned_count"] == 1 for team in payload["teams"]))
        self.assertLessEqual(len(selects), 5, selects)
        group_aggregates = [
            statement
            for statement in selects
            if "left outer join tickets" in statement
            and "group by external_groups.id" in statement
        ]
        self.assertEqual(len(group_aggregates), 1, selects)

        # Truncating navigation metadata must not truncate authorization. A
        # direct team deep link still uses the correlated membership predicate.
        target_index = scale_group_count - 1
        target = self.client.get("/agent-workspace/tickets", params={
            "scope": "team",
            "team_id": f"scale-group-{target_index:03d}",
        })
        self.assertEqual(target.status_code, 200, target.text)
        self.assertEqual(
            [ticket["id"] for ticket in target.json()],
            [f"scale-ticket-{target_index:03d}"],
        )

        # Global and Problem-linked ticket responses build their redaction
        # context from this bounded result page, not the first 100 directory
        # groups. AI fields remain visible for a legitimate deep team ticket.
        global_ticket = self.client.get("/tickets", params={
            "search": f"Scale team ticket {target_index:03d}",
            "limit": 1,
        })
        problem_ticket = self.client.get("/problems/scale-problem/tickets")
        self.assertEqual(global_ticket.status_code, 200, global_ticket.text)
        self.assertEqual(problem_ticket.status_code, 200, problem_ticket.text)
        self.assertEqual(global_ticket.json()[0]["summary"], "Deep team summary")
        self.assertEqual(problem_ticket.json()[0]["summary"], "Deep team summary")

    def test_ticket_payload_fetches_only_latest_public_conversation_direction(self):
        now = datetime.utcnow()
        conversation_count = 250
        with self.session_factory() as db:
            conversations = []
            for index in range(conversation_count):
                conversations.append(ExternalConversationRecord(
                    id=f"scale-conversation-{index:04d}",
                    binding_id="binding-one",
                    provider="freshservice",
                    ticket_id="local-mine",
                    provider_ticket_id="local-mine",
                    external_id=f"public-{index:04d}",
                    body=f"Public message {index}",
                    body_hash=f"{index:064x}",
                    is_private=False,
                    incoming=index != conversation_count - 1,
                    provider_created_at=now + timedelta(seconds=index),
                    deleted=False,
                    public_tombstone=False,
                    revision_hash=f"{index + 1:064x}",
                    received_at=now + timedelta(seconds=index),
                ))
            for suffix, values in (
                ("private", {"is_private": True}),
                ("deleted", {"deleted": True}),
                ("tombstone", {"public_tombstone": True}),
            ):
                conversations.append(ExternalConversationRecord(
                    id=f"newer-{suffix}",
                    binding_id="binding-one",
                    provider="freshservice",
                    ticket_id="local-mine",
                    provider_ticket_id="local-mine",
                    external_id=f"newer-{suffix}",
                    body="Excluded newer incoming message",
                    body_hash=(suffix[0] * 64),
                    is_private=values.get("is_private", False),
                    incoming=True,
                    provider_created_at=now + timedelta(hours=1),
                    deleted=values.get("deleted", False),
                    public_tombstone=values.get("public_tombstone", False),
                    revision_hash=(suffix[-1] * 64),
                    received_at=now + timedelta(hours=1),
                ))
            db.add_all(conversations)
            db.commit()

        selects = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(" ".join(statement.lower().split()))

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get("/agent-workspace/tickets", params={
                "scope": "mine",
                "ticket_id": "local-mine",
            })
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        self.assertFalse(response.json()[0]["needs_reply"])
        ranked_queries = [statement for statement in selects if "row_number() over" in statement]
        self.assertEqual(len(ranked_queries), 1, selects)
        self.assertIn("partition by external_conversations.ticket_id", ranked_queries[0])
        self.assertNotIn("external_conversations.body", ranked_queries[0])
        self.assertLessEqual(len(selects), 8, selects)

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
