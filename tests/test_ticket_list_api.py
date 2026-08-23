import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, TicketRecord, UserRecord, get_db


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
            target.ai_suggested_category = "Network"
            target.ai_status = "completed"
            # This value would also match INC_100% if SQL wildcard characters
            # from user input were not escaped.
            tickets[101].external_id = "INCX100A"
            db.add_all(tickets)
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
        self.assertEqual(response.json()[0]["recommended_team"], "Network Operations")
        self.assertEqual(response.json()[0]["recommended_team_basis"], "ai_category")

    def test_team_falls_back_when_ai_category_is_missing_or_stale(self):
        ready = self.client.get("/tickets/ticket-100").json()
        fallback = self.client.get("/tickets/ticket-099").json()

        self.assertEqual(ready["recommended_team"], "Network Operations")
        self.assertEqual(fallback["recommended_team"], "Service Desk")
        self.assertEqual(fallback["recommended_team_basis"], "fallback")

    def test_team_mapping_uses_only_valid_ai_issue_type(self):
        expected = {
            "Network": "Network Operations",
            "Access Request": "Identity and Access",
            "Hardware": "Workplace Technology",
            "Software": "Application Support",
        }
        for issue_type, team in expected.items():
            with self.subTest(issue_type=issue_type):
                self.assertEqual(main.intel.recommended_team(issue_type, "completed"), (team, "ai_category"))
        self.assertEqual(main.intel.recommended_team("Other", "completed"), ("Service Desk", "fallback"))
        self.assertEqual(main.intel.recommended_team("Network", "stale"), ("Service Desk", "fallback"))

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

    def test_priority_sort_is_semantic_and_stable(self):
        response = self.client.get(
            "/tickets", params={"sort": "priority", "limit": 105}
        )

        priorities = [ticket["priority"] for ticket in response.json()]
        ranks = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        self.assertEqual([ranks[value] for value in priorities], sorted(ranks[value] for value in priorities))

    def test_assignee_enrichment_uses_one_batched_query(self):
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
        self.assertEqual(len(select_statements), 2)
        self.assertTrue(all(ticket["assignee_name"] for ticket in response.json()))


if __name__ == "__main__":
    unittest.main()
