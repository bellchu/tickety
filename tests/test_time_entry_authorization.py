import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    ExternalGroupRecord,
    TicketRecord,
    TimeEntryRecord,
    UserRecord,
    get_db,
)


class TimeEntryAuthorizationTests(unittest.TestCase):
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
            db.add_all([
                UserRecord(id="admin", name="Admin", role="admin", is_active=True),
                UserRecord(
                    id="supervisor", name="Supervisor", role="supervisor", is_active=True
                ),
                UserRecord(id="agent-a", name="Agent A", role="agent", is_active=True),
                UserRecord(id="agent-b", name="Agent B", role="agent", is_active=True),
                ExternalGroupRecord(
                    id="team-one",
                    binding_id="binding-one",
                    provider="freshservice",
                    external_id="2001",
                    name="Service Desk",
                    profile_json="{}",
                    active=True,
                    fetched_at=now,
                ),
                ExternalGroupRecord(
                    id="team-two",
                    binding_id="binding-one",
                    provider="freshservice",
                    external_id="2002",
                    name="Infrastructure",
                    profile_json="{}",
                    active=True,
                    fetched_at=now,
                ),
                TicketRecord(
                    id="ticket-a",
                    subject="Agent A ticket",
                    assignee_id="agent-a",
                    binding_id="binding-one",
                    external_source="freshservice",
                    external_group_id="2001",
                ),
                TicketRecord(
                    id="ticket-b",
                    subject="Agent B team-one ticket",
                    assignee_id="agent-b",
                    binding_id="binding-one",
                    external_source="freshservice",
                    external_group_id="2001",
                ),
                TicketRecord(
                    id="ticket-outside",
                    subject="Agent B team-two ticket",
                    assignee_id="agent-b",
                    binding_id="binding-one",
                    external_source="freshservice",
                    external_group_id="2002",
                ),
            ])
            db.flush()
            db.add_all([
                TimeEntryRecord(
                    ticket_id="ticket-a",
                    user_id="agent-a",
                    description="Agent A private work note",
                    minutes=60,
                    entry_date=now,
                ),
                TimeEntryRecord(
                    ticket_id="ticket-b",
                    user_id="agent-b",
                    description="Agent B team-one work note",
                    minutes=120,
                    entry_date=now,
                ),
                TimeEntryRecord(
                    ticket_id="ticket-outside",
                    user_id="agent-b",
                    description="Agent B team-two work note",
                    minutes=180,
                    entry_date=now,
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
            id="agent-a", name="Agent A", role="agent", is_active=True
        )
        main.app.dependency_overrides[get_db] = override_db
        main.app.dependency_overrides[main.get_current_user] = lambda: self.current_user
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.roles_patch = patch.object(main, "_roles_required_for_request", return_value=None)
        self.roles_patch.start()
        self.client = TestClient(main.app)
        self.headers = {"Sec-Fetch-Site": "same-origin"}

    def tearDown(self):
        self.roles_patch.stop()
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _as(self, user_id: str, role: str):
        self.current_user = UserRecord(
            id=user_id,
            name=user_id,
            role=role,
            is_active=True,
        )

    def test_agent_list_ticket_and_summary_are_forced_to_own_entries(self):
        listed = self.client.get("/time-entries")
        ticket_entries = self.client.get("/time-entries/ticket/ticket-b")
        summary = self.client.get("/time-entries/summary", params={"time_zone": "UTC"})

        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(
            [entry["description"] for entry in listed.json()],
            ["Agent A private work note"],
        )
        self.assertEqual(ticket_entries.status_code, 200, ticket_entries.text)
        self.assertEqual(ticket_entries.json(), [])
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json(), {
            "total_hours": 1.0,
            "today_hours": 1.0,
            "ticket_count": 1,
            "average_hours_per_ticket": 1.0,
        })

    def test_agent_cannot_select_user_or_team_reporting_scope(self):
        for path, params in (
            ("/time-entries", {"user_id": "agent-b"}),
            ("/time-entries", {"team_id": "team-one"}),
            ("/time-entries/ticket/ticket-a", {"user_id": "agent-a"}),
            ("/time-entries/summary", {"user_id": "agent-b"}),
            ("/time-entries/summary", {"team_id": "team-one"}),
        ):
            with self.subTest(path=path, params=params):
                response = self.client.get(path, params=params)
                self.assertEqual(response.status_code, 403, response.text)

    def test_supervisor_can_narrow_list_and_summary_to_matching_scopes(self):
        self._as("supervisor", "supervisor")

        all_entries = self.client.get("/time-entries")
        user_entries = self.client.get("/time-entries", params={"user_id": "agent-b"})
        team_entries = self.client.get("/time-entries", params={"team_id": "team-one"})
        combined = self.client.get(
            "/time-entries",
            params={"user_id": "agent-b", "team_id": "team-one"},
        )
        team_summary = self.client.get(
            "/time-entries/summary",
            params={"time_zone": "UTC", "team_id": "team-one"},
        )
        ticket_summary = self.client.get(
            "/time-entries/summary",
            params={
                "time_zone": "UTC",
                "ticket_id": "ticket-b",
                "user_id": "agent-b",
            },
        )

        self.assertEqual(len(all_entries.json()), 3)
        self.assertEqual({entry["user_id"] for entry in user_entries.json()}, {"agent-b"})
        self.assertEqual(
            {entry["ticket_id"] for entry in team_entries.json()},
            {"ticket-a", "ticket-b"},
        )
        self.assertEqual(
            [entry["ticket_id"] for entry in combined.json()],
            ["ticket-b"],
        )
        self.assertEqual(
            team_summary.json(), {
                "total_hours": 3.0,
                "today_hours": 3.0,
                "ticket_count": 2,
                "average_hours_per_ticket": 1.5,
            }
        )
        self.assertEqual(
            ticket_summary.json(), {
                "total_hours": 2.0,
                "today_hours": 2.0,
                "ticket_count": 1,
                "average_hours_per_ticket": 2.0,
            }
        )

    def test_time_entry_lists_page_past_the_previous_silent_cap(self):
        with self.session_factory() as db:
            db.add_all([
                TimeEntryRecord(
                    ticket_id="ticket-a",
                    user_id="agent-a",
                    description=f"Paged work note {index:03d}",
                    minutes=1,
                    entry_date=datetime.utcnow(),
                )
                for index in range(205)
            ])
            db.commit()

        pages = [
            self.client.get("/time-entries", params={"limit": 100, "offset": offset})
            for offset in (0, 100, 200)
        ]

        for response in pages:
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["x-page-limit"], "100")
        self.assertEqual(
            [response.headers["x-page-offset"] for response in pages],
            ["0", "100", "200"],
        )
        self.assertEqual(
            [response.headers["x-has-more"] for response in pages],
            ["true", "true", "false"],
        )
        self.assertEqual([len(response.json()) for response in pages], [100, 100, 6])
        entry_ids = [entry["id"] for response in pages for entry in response.json()]
        self.assertEqual(len(entry_ids), 206)
        self.assertEqual(len(set(entry_ids)), 206)

        ticket_page = self.client.get(
            "/time-entries/ticket/ticket-a",
            params={"limit": 25, "offset": 200},
        )
        self.assertEqual(ticket_page.status_code, 200, ticket_page.text)
        self.assertEqual(len(ticket_page.json()), 6)
        self.assertEqual(ticket_page.headers["x-page-limit"], "25")
        self.assertEqual(ticket_page.headers["x-page-offset"], "200")
        self.assertEqual(ticket_page.headers["x-has-more"], "false")

    def test_time_entry_page_bounds_are_validated(self):
        for path in ("/time-entries", "/time-entries/ticket/ticket-a"):
            with self.subTest(path=path, parameter="limit"):
                response = self.client.get(path, params={"limit": 201})
                self.assertEqual(response.status_code, 422, response.text)
            with self.subTest(path=path, parameter="offset"):
                response = self.client.get(path, params={"offset": -1})
                self.assertEqual(response.status_code, 422, response.text)

    def test_sql_bound_request_ids_reject_nul_and_normalize_whitespace(self):
        self._as("supervisor", "supervisor")

        invalid_query = self.client.get("/time-entries?ticket_id=bad%00ticket")
        invalid_path = self.client.get("/time-entries/ticket/bad%00ticket")
        normalized = self.client.get(
            "/time-entries",
            params={"ticket_id": "  ticket-a  ", "user_id": "  agent-a  "},
        )

        self.assertEqual(invalid_query.status_code, 422, invalid_query.text)
        self.assertEqual(invalid_path.status_code, 422, invalid_path.text)
        self.assertEqual(normalized.status_code, 200, normalized.text)
        self.assertEqual(
            [entry["ticket_id"] for entry in normalized.json()],
            ["ticket-a"],
        )

    def test_agent_can_log_only_against_work_they_are_allowed_to_perform(self):
        allowed = self.client.post(
            "/time-entries",
            headers=self.headers,
            json={
                "ticket_id": "ticket-a",
                "description": "Additional assigned work",
                "minutes": 30,
            },
        )
        forbidden = self.client.post(
            "/time-entries",
            headers=self.headers,
            json={
                "ticket_id": "ticket-b",
                "description": "Should not be accepted",
                "minutes": 30,
            },
        )

        self.assertEqual(allowed.status_code, 201, allowed.text)
        self.assertEqual(allowed.json()["user_id"], "agent-a")
        self.assertEqual(forbidden.status_code, 403, forbidden.text)
        with self.session_factory() as db:
            self.assertEqual(
                db.query(TimeEntryRecord)
                .filter(TimeEntryRecord.user_id == "agent-a")
                .count(),
                2,
            )

    def test_admin_can_log_against_any_ticket(self):
        self._as("admin", "admin")

        response = self.client.post(
            "/time-entries",
            headers=self.headers,
            json={
                "ticket_id": "ticket-b",
                "description": "Administrative correction",
                "minutes": 15,
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["user_id"], "admin")

    def test_time_entry_input_is_bounded(self):
        cases = (
            {
                "ticket_id": "ticket-a",
                "description": "Too many minutes",
                "minutes": 1_441,
            },
            {
                "ticket_id": "ticket-a",
                "description": "x" * 10_001,
                "minutes": 1,
            },
            {
                "ticket_id": "ticket-a",
                "description": "   ",
                "minutes": 1,
            },
            {
                "ticket_id": "ticket-a",
                "description": "invalid\u0000description",
                "minutes": 1,
            },
        )
        for payload in cases:
            with self.subTest(minutes=payload["minutes"], length=len(payload["description"])):
                response = self.client.post(
                    "/time-entries", headers=self.headers, json=payload
                )
                self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
