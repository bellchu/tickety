import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    ExternalUserRecord,
    TicketCommentRecord,
    TicketPriorityConfigRecord,
    TicketRecord,
    TicketStatusConfigRecord,
    UserRecord,
    get_db,
)


class TicketListApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        created = datetime(2026, 1, 1, 12, 0, 0)

        with self.session_factory() as db:
            db.add_all([
                UserRecord(
                    id="test-admin",
                    name="Test Admin",
                    role="admin",
                    is_active=True,
                ),
                UserRecord(id="agent-a", name="Alice Agent"),
                UserRecord(id="agent-b", name="Bob Agent"),
            ])
            priorities = ["P1", "P2", "P3", "P4"]
            tickets = []
            for index in range(105):
                tickets.append(TicketRecord(
                    id=f"ticket-{index:03d}",
                    subject=f"Ticket {index}",
                    description="Routine request",
                    reporter=f"reporter-{index}@example.com",
                    status="Open",
                    priority=priorities[index % len(priorities)],
                    category="General",
                    assignee_id="agent-a" if index % 2 == 0 else "agent-b",
                    external_id=f"EXT-{index:03d}",
                    created_at=created + timedelta(minutes=index),
                    updated_at=created + timedelta(minutes=index),
                ))

            target = tickets[100]
            target.description = "Replication lag detected in primary database"
            target.status = "Escalated"
            target.priority = "P1"
            target.category = "Database"
            target.assignee_id = "agent-b"
            target.external_id = "INC_100%"
            target.external_source = "freshservice"
            target.external_requester_id = "requester-100"
            target.external_created_at = created + timedelta(minutes=100)
            target.ai_suggested_category = "Network"
            target.ai_suggested_team = "INFRASTRUCTURE_OPERATIONS"
            target.ai_secondary_team = None
            target.ai_routing_confidence = 0.94
            target.ai_routing_scope = "service_wide"
            target.ai_affected_service = "database platform"
            target.ai_failure_domain = "replication failure"
            target.ai_routing_reason = "Replication lag is observed on the database platform."
            target.ai_status = "completed"
            for index, subject in zip(
                (90, 91, 92, 93),
                (
                    "Device scanner allocation failure",
                    "legacy platform batch job needs development support",
                    "Billing workflow workflow defect",
                    "Deployment pipeline build failure",
                ),
            ):
                tickets[index].subject = subject
                tickets[index].ai_suggested_category = "Other"
                tickets[index].ai_status = "completed"
            # This value would also match INC_100% if SQL wildcard characters
            # from user input were not escaped.
            tickets[101].external_id = "INCX100A"
            db.add_all(tickets)
            db.flush()
            main._record_ai_artifact(
                db,
                target,
                "route",
                {
                    "primary_group": target.ai_suggested_team,
                    "secondary_group": target.ai_secondary_team,
                    "confidence": target.ai_routing_confidence,
                    "scope": target.ai_routing_scope,
                    "affected_service": target.ai_affected_service,
                    "failure_domain": target.ai_failure_domain,
                    "reason": target.ai_routing_reason,
                },
                "unused",
            )
            db.add(ExternalUserRecord(
                id="external-requester-100",
                binding_id="legacy",
                provider="freshservice",
                external_id="requester-100",
                user_type="requester",
                name="Riley Requester",
                email="riley.requester@example.com",
                title="Finance Director",
                profile_json="{}",
            ))
            db.add(TicketCommentRecord(
                ticket_id="ticket-100",
                author_name="Riley Requester",
                body="Following up with more detail",
                is_private=False,
                created_at=created + timedelta(minutes=200),
            ))
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        main.app.dependency_overrides[main.get_current_user] = lambda: UserRecord(
            id="test-admin", name="Test Admin", role="admin", is_active=True
        )
        main.app.dependency_overrides[main.get_protected_ai_user] = lambda: UserRecord(
            id="test-admin", name="Test Admin", role="admin", is_active=True
        )
        self.auth_middleware_patch = patch.object(
            main,
            "_auth_required_for_request",
            return_value=False,
        )
        self.auth_middleware_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.auth_middleware_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_default_page_is_bounded_and_reports_more_results(self):
        response = self.client.get("/tickets")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 100)
        self.assertEqual(response.headers["x-page-limit"], "100")
        self.assertEqual(response.headers["x-page-offset"], "0")
        self.assertEqual(response.headers["x-has-more"], "true")

        next_page = self.client.get("/tickets", params={"limit": 100, "offset": 100})
        self.assertEqual(len(next_page.json()), 5)
        self.assertEqual(next_page.headers["x-has-more"], "false")

    def test_pagination_and_sort_parameters_are_validated(self):
        for params in (
            {"limit": 0},
            {"limit": 501},
            {"offset": -1},
            {"offset": 1_000_001},
            {"sort": "arbitrary-sql"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/tickets", params=params).status_code, 422)

    def test_queue_sort_and_dashboard_summary_do_not_silently_truncate(self):
        queue = self.client.get("/tickets", params={"sort": "queue", "limit": 10})
        summary = self.client.get("/dashboard/summary")

        self.assertEqual(queue.status_code, 200)
        self.assertEqual(
            [ticket["id"] for ticket in queue.json()[:3]],
            ["ticket-000", "ticket-004", "ticket-008"],
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json(), {
            "total_tickets": 105,
            "active_tickets": 105,
            "inactive_tickets": 0,
            "p1_active": 27,
            "escalated_active": 1,
            "unassigned_active": 0,
        })

        with self.session_factory() as db:
            db.get(TicketRecord, "ticket-000").status = "Closed"
            unassigned = db.get(TicketRecord, "ticket-001")
            unassigned.assignee_id = None
            unassigned.external_assignee_id = None
            db.commit()

        updated = self.client.get("/dashboard/summary")
        self.assertEqual(updated.json(), {
            "total_tickets": 105,
            "active_tickets": 104,
            "inactive_tickets": 1,
            "p1_active": 26,
            "escalated_active": 1,
            "unassigned_active": 1,
        })

    def test_dashboard_terminal_counts_use_portable_ascii_keys(self):
        with self.session_factory() as db:
            db.add(TicketStatusConfigRecord(
                name="K",
                name_key="k",
                label="Terminal K",
                is_open=False,
                is_terminal=True,
            ))
            db.get(TicketRecord, "ticket-000").status = "K"
            db.get(TicketRecord, "ticket-001").status = "K"
            db.commit()

        response = self.client.get("/dashboard/summary")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["inactive_tickets"], 1)
        self.assertEqual(response.json()["active_tickets"], 104)

    def test_filters_are_combined_server_side(self):
        response = self.client.get("/tickets", params={
            "status": "Escalated",
            "priority": "P1",
            "category": "Database",
            "assignee_id": "agent-b",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual([ticket["id"] for ticket in response.json()], ["ticket-100"])
        self.assertEqual(response.json()[0]["assignee_name"], "Bob Agent")
        self.assertEqual(response.json()[0]["recommended_team"], "INFRASTRUCTURE_OPERATIONS")
        self.assertEqual(response.json()[0]["recommended_team_basis"], "ai_team")
        self.assertEqual(response.json()[0]["routing_status"], "ai_team_recommendation")
        self.assertFalse(response.json()[0]["routing_catalog_validated"])
        self.assertEqual(response.json()[0]["requester_name"], "Riley Requester")
        self.assertEqual(response.json()[0]["requester_email"], "riley.requester@example.com")
        self.assertEqual(response.json()[0]["requester_title"], "Finance Director")
        self.assertEqual(
            response.json()[0]["last_communication_at"],
            "2026-01-01T15:20:00",
        )

    def test_team_requires_a_complete_current_route_artifact(self):
        ready = self.client.get("/tickets/ticket-100").json()
        unrouted = self.client.get("/tickets/ticket-099").json()

        self.assertEqual(ready["recommended_team"], "INFRASTRUCTURE_OPERATIONS")
        self.assertEqual(unrouted["recommended_team"], "Unrouted / Review")
        self.assertEqual(unrouted["recommended_team_basis"], "unrouted_review")
        self.assertEqual(unrouted["routing_status"], "unrouted_review")
        self.assertEqual(
            unrouted["routing_abstention_reason"],
            "untrusted_ai_status",
        )

    def test_current_route_remains_projected_while_later_artifact_is_queued(self):
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "ticket-099")
            ticket.ai_suggested_team = "SOFTWARE_ENGINEERING"
            ticket.ai_secondary_team = None
            ticket.ai_routing_confidence = 0.89
            ticket.ai_routing_scope = "single_user"
            ticket.ai_affected_service = "support portal"
            ticket.ai_failure_domain = "web application failure"
            ticket.ai_routing_reason = "The failure is observed in the support portal."
            ticket.ai_status = "queued"
            ticket.ai_requested_artifacts = "summary"
            db.flush()
            main._record_ai_artifact(
                db,
                ticket,
                "route",
                {
                    "primary_group": "SOFTWARE_ENGINEERING",
                    "secondary_group": None,
                    "confidence": 0.89,
                    "scope": "single_user",
                    "affected_service": "support portal",
                    "failure_domain": "web application failure",
                    "reason": "The failure is observed in the support portal.",
                },
                "unused",
            )
            db.commit()

        routed = self.client.get("/tickets/ticket-099").json()

        self.assertEqual(routed["recommended_team"], "SOFTWARE_ENGINEERING")
        self.assertEqual(routed["recommended_team_basis"], "ai_team")
        self.assertEqual(routed["routing_status"], "ai_team_recommendation")

    def test_enterprise_and_development_tickets_never_default_to_service_desk(self):
        for index in (90, 91, 92, 93):
            with self.subTest(ticket=index):
                ticket = self.client.get(f"/tickets/ticket-{index:03d}").json()
                self.assertEqual(ticket["recommended_team"], "Unrouted / Review")
                self.assertEqual(ticket["recommended_team_basis"], "unrouted_review")
                self.assertEqual(
                    ticket["routing_abstention_reason"],
                    "untrusted_ai_status",
                )
                self.assertNotEqual(ticket["recommended_team"], "Service Desk")

    def test_team_projection_uses_only_current_closed_set_resolver_codes(self):
        for resolver_group in main.intel.AI_RESOLVER_TEAMS:
            with self.subTest(resolver_group=resolver_group):
                self.assertEqual(
                    main.intel.recommended_team(
                        None,
                        "completed",
                        ai_suggested_team=resolver_group,
                        ai_evidence_current=True,
                    ),
                    (resolver_group, "ai_team"),
                )
        self.assertEqual(
            main.intel.recommended_team(
                None,
                "completed",
                ai_suggested_team="Network Operations",
                ai_evidence_current=True,
            ),
            ("Unrouted / Review", "unrouted_review"),
        )
        self.assertEqual(
            main.intel.recommended_team(
                None,
                "completed",
                ai_suggested_team="SOFTWARE_ENGINEERING",
                ai_evidence_current=False,
            ),
            ("Unrouted / Review", "unrouted_review"),
        )

    def test_routing_uses_current_route_not_source_assignment_or_category(self):
        assigned = main.intel.team_routing_decision(
            None,
            "completed",
            ai_suggested_team="APPLICATION_OPERATIONS",
            source_group_id="2000245797",
            source_category="E1 App",
            ticket_status="Open",
            ai_evidence_current=True,
        )
        self.assertEqual(assigned.recommended_team, "APPLICATION_OPERATIONS")
        self.assertEqual(assigned.basis, "ai_team")
        self.assertEqual(assigned.status, "ai_team_recommendation")
        self.assertIsNone(assigned.abstention_reason)

        source = main.intel.team_routing_decision(
            None,
            None,
            source_category="Hardware - Printers",
            ticket_status="Open",
        )
        self.assertEqual(source.recommended_team, "Unrouted / Review")
        self.assertEqual(source.basis, "unrouted_review")
        self.assertEqual(source.status, "unrouted_review")
        self.assertEqual(source.abstention_reason, "untrusted_ai_status")

        ambiguous = main.intel.team_routing_decision(
            "Other",
            "completed",
            source_category="Infrastructure",
            ticket_status="Open",
        )
        self.assertEqual(ambiguous.recommended_team, "Unrouted / Review")
        self.assertEqual(ambiguous.abstention_reason, "untrusted_ai_status")

        closed = main.intel.team_routing_decision(
            None,
            None,
            source_group_id="2000241178",
            source_category=None,
            ticket_status="Closed",
        )
        self.assertEqual(closed.recommended_team, "No active routing")
        self.assertEqual(closed.basis, "not_applicable")
        self.assertEqual(closed.status, "not_applicable")

    def test_related_tickets_are_bounded_deduplicated_and_authoritative(self):
        retrieval = {
            "match_method": "vector",
            "results": [
                {"source_type": "ticket", "ticket_id": "ticket-100", "score": 0.99, "match_method": "vector"},
                {"source_type": "ticket", "ticket_id": "ticket-099", "score": 0.91, "match_method": "vector"},
                {"source_type": "ticket", "ticket_id": "ticket-099", "score": 0.90, "match_method": "vector"},
                {"source_type": "comment", "ticket_id": "ticket-098", "score": 0.89, "match_method": "vector"},
            ],
        }
        with patch.object(
            main.ticket_vectors,
            "retrieve_ticket_context",
            new=AsyncMock(return_value=retrieval),
        ) as retrieve:
            response = self.client.get("/tickets/ticket-100/related", params={"limit": 5})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["match_method"], "vector")
        self.assertEqual([item["ticket_id"] for item in payload["items"]], ["ticket-099"])
        self.assertEqual(payload["items"][0]["subject"], "Ticket 99")
        kwargs = retrieve.await_args.kwargs
        self.assertEqual(kwargs["limit"], 15)
        self.assertEqual(kwargs["source_types"], ["ticket"])
        self.assertFalse(kwargs["include_private_comments"])

    def test_related_tickets_failure_is_sanitized(self):
        with patch.object(
            main.ticket_vectors,
            "retrieve_ticket_context",
            new=AsyncMock(side_effect=RuntimeError("provider secret")),
        ):
            response = self.client.get("/tickets/ticket-100/related")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "related_tickets_unavailable")
        self.assertNotIn("provider secret", response.text)

    def test_searches_text_and_identifiers_with_literal_wildcards(self):
        description_match = self.client.get(
            "/tickets", params={"search": "replication lag"}
        )
        self.assertEqual(
            [ticket["id"] for ticket in description_match.json()],
            ["ticket-100"],
        )

        identifier_match = self.client.get(
            "/tickets", params={"search": "INC_100%"}
        )
        self.assertEqual(
            [ticket["id"] for ticket in identifier_match.json()],
            ["ticket-100"],
        )

        requester_match = self.client.get(
            "/tickets", params={"search": "Finance Director"}
        )
        self.assertEqual(
            [ticket["id"] for ticket in requester_match.json()],
            ["ticket-100"],
        )

    def test_priority_sort_is_semantic_and_stable(self):
        response = self.client.get(
            "/tickets", params={"sort": "priority", "limit": 105}
        )

        priorities = [ticket["priority"] for ticket in response.json()]
        ranks = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        self.assertEqual([ranks[value] for value in priorities], sorted(ranks[value] for value in priorities))

    def test_priority_sort_honors_configured_custom_weight(self):
        with self.session_factory() as db:
            db.add(TicketPriorityConfigRecord(
                name="Severity Zero",
                label="Severity zero",
                color="red",
                weight=2,
                sort_order=99,
            ))
            db.add(TicketRecord(
                id="ticket-custom-priority",
                subject="Custom priority incident",
                description="Uses an administrator-defined queue priority",
                reporter="operator@example.com",
                status="Open",
                priority="severity zero",
                category="General",
                assignee_id="agent-a",
                created_at=datetime(2026, 1, 2, 12, 0, 0),
                updated_at=datetime(2026, 1, 2, 12, 0, 0),
            ))
            db.commit()

        response = self.client.get(
            "/tickets", params={"sort": "priority", "limit": 106}
        )

        self.assertEqual(response.status_code, 200)
        priorities = [ticket["priority"] for ticket in response.json()]
        custom_index = priorities.index("severity zero")
        self.assertTrue(all(value == "P1" for value in priorities[:custom_index]))
        self.assertEqual(priorities[custom_index + 1], "P2")

    def test_ticket_enrichment_uses_only_batched_queries(self):
        select_statements = []

        def track_selects(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                select_statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", track_selects)
        try:
            response = self.client.get("/tickets", params={"limit": 50})
        finally:
            event.remove(self.engine, "before_cursor_execute", track_selects)

        self.assertEqual(response.status_code, 200)
        # Ticket page, dynamic terminal-status policy, local owners, provider
        # profiles, public-comment times, and current triage provenance. No row
        # causes an N+1 query.
        self.assertEqual(len(select_statements), 6)
        self.assertTrue(all(ticket["assignee_name"] for ticket in response.json()))


if __name__ == "__main__":
    unittest.main()
