import csv
import io
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
    SurveyRecord,
    SurveyResponseRecord,
    TicketRecord,
    UserRecord,
    get_db,
)


class ReportsApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.now = datetime.utcnow().replace(second=0, microsecond=0)

        with self.session_factory() as db:
            db.add_all([
                UserRecord(id="admin", name="Admin", role="admin", is_active=True),
                UserRecord(id="agent-one", name="Agent One", role="agent", is_active=True),
                UserRecord(id="agent-two", name="Agent Two", role="agent", is_active=True),
            ])
            db.add_all([
                TicketRecord(
                    id="recent-open",
                    subject="Recent network issue",
                    status="Open",
                    priority="P1",
                    category="Network",
                    assignee_id="agent-one",
                    created_at=self.now - timedelta(days=2),
                    resolution_due_at=self.now - timedelta(hours=1),
                ),
                TicketRecord(
                    id="recent-resolved",
                    external_id="FS-200",
                    subject="=2+2",
                    status="Closed",
                    priority="P2",
                    category="Applications",
                    assignee_id="agent-one",
                    external_source="freshservice",
                    created_at=self.now - timedelta(days=5),
                    external_created_at=self.now - timedelta(days=5),
                    resolved_at=self.now - timedelta(hours=3),
                    external_resolved_at=self.now - timedelta(hours=3),
                    resolution_due_at=self.now - timedelta(days=1),
                ),
                TicketRecord(
                    id="old-created-recently-resolved",
                    subject="Long-running legacy issue",
                    status="Closed",
                    priority="P3",
                    category="Legacy",
                    assignee_id="agent-two",
                    created_at=self.now - timedelta(days=4000),
                    resolved_at=self.now - timedelta(hours=2),
                    resolution_due_at=self.now - timedelta(days=5),
                ),
                TicketRecord(
                    id="other-agent",
                    subject="Escalated database issue",
                    status="Escalated",
                    priority="P1",
                    category="Database",
                    assignee_id="agent-two",
                    created_at=self.now - timedelta(days=1),
                ),
                TicketRecord(
                    id="unassigned",
                    subject="Unassigned request",
                    status="Open",
                    priority="P4",
                    category="General",
                    assignee_id=None,
                    created_at=self.now - timedelta(hours=6),
                ),
            ])
            db.add_all([
                SurveyRecord(id="recent-survey", ticket_id="recent-resolved"),
                SurveyRecord(id="old-survey", ticket_id="old-created-recently-resolved"),
            ])
            db.add_all([
                SurveyResponseRecord(survey_id="recent-survey", rating=5),
                SurveyResponseRecord(survey_id="old-survey", rating=1),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        self.admin = UserRecord(id="admin", name="Admin", role="admin", is_active=True)
        main.app.dependency_overrides[get_db] = override_db
        main.app.dependency_overrides[main.get_current_user] = lambda: self.admin
        main.app.dependency_overrides[main.get_protected_ai_user] = lambda: self.admin
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.analytics_patch = patch.object(main, "_reserve_analytics_request")
        self.auth_patch.start()
        self.analytics_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.analytics_patch.stop()
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def period(self, days=7, **extra):
        params = {
            "start_at": (self.now - timedelta(days=days)).isoformat() + "Z",
            "end_at": (self.now + timedelta(minutes=1)).isoformat() + "Z",
        }
        params.update(extra)
        return params

    def test_default_period_excludes_decade_old_created_ticket(self):
        response = self.client.get("/reports/summary")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_tickets"], 4)
        self.assertEqual(response.json()["csat_proxy"], 100.0)

    def test_all_report_sections_apply_the_same_criteria(self):
        params = self.period(
            status="Open",
            priority="P1",
            category="Network",
        )

        summary = self.client.get("/reports/summary", params=params)
        volume = self.client.get("/reports/volume", params=params)
        categories = self.client.get("/reports/by-category", params=params)
        statuses = self.client.get("/reports/by-status", params=params)
        sla = self.client.get("/reports/sla-compliance", params=params)
        resolution = self.client.get("/reports/resolution-time", params=params)

        self.assertEqual(summary.json()["total_tickets"], 1)
        self.assertEqual(sum(volume.json()["counts"]), 1)
        self.assertEqual(categories.json()["categories"], ["Network"])
        self.assertEqual(categories.json()["counts"], [1])
        self.assertEqual(statuses.json(), {"statuses": ["Open"], "counts": [1]})
        self.assertEqual(sla.json()["P1"], {"total": 1, "breached": 1, "compliance": 0.0})
        self.assertEqual(resolution.json()["total_matching_tickets"], 0)

    def test_resolved_time_basis_can_find_old_created_ticket(self):
        params = self.period(days=1, date_field="resolved")

        resolved_basis = self.client.get("/reports/summary", params=params)
        created_basis = self.client.get(
            "/reports/summary",
            params={**params, "date_field": "created"},
        )

        self.assertEqual(resolved_basis.json()["total_tickets"], 2)
        self.assertEqual(created_basis.json()["total_tickets"], 2)
        self.assertEqual(resolved_basis.json()["resolved_tickets"], 2)
        self.assertEqual(created_basis.json()["resolved_tickets"], 0)

    def test_csv_export_matches_filters_and_escapes_spreadsheet_formulas(self):
        response = self.client.get(
            "/reports/export",
            params=self.period(status="Closed"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/csv"))
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertEqual(response.headers["x-report-rows"], "1")
        rows = list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
        self.assertEqual(rows[0][0:3], ["Ticket ID", "External ID", "Subject"])
        self.assertEqual(rows[1][0], "recent-resolved")
        self.assertEqual(rows[1][2], "'=2+2")
        self.assertNotIn("old-created-recently-resolved", response.text)

    def test_agent_reports_and_exports_are_scoped_to_own_and_unassigned_tickets(self):
        agent = UserRecord(id="agent-one", name="Agent One", role="agent", is_active=True)
        main.app.dependency_overrides[main.get_current_user] = lambda: agent

        summary = self.client.get("/reports/summary", params=self.period())
        exported = self.client.get("/reports/export", params=self.period())

        self.assertEqual(summary.json()["total_tickets"], 3)
        self.assertIn("recent-open", exported.text)
        self.assertIn("unassigned", exported.text)
        self.assertNotIn("other-agent", exported.text)

    def test_export_refuses_to_silently_truncate_large_results(self):
        with patch.object(main, "_REPORT_EXPORT_LIMIT", 1):
            response = self.client.get("/reports/export", params=self.period())

        self.assertEqual(response.status_code, 422)
        self.assertIn("narrow the date range", response.json()["detail"])

    def test_invalid_period_and_date_basis_are_rejected(self):
        reversed_period = self.client.get("/reports/summary", params={
            "start_at": self.now.isoformat(),
            "end_at": (self.now - timedelta(days=1)).isoformat(),
        })
        invalid_basis = self.client.get(
            "/reports/summary",
            params=self.period(date_field="updated"),
        )

        self.assertEqual(reversed_period.status_code, 422)
        self.assertEqual(invalid_basis.status_code, 422)


if __name__ == "__main__":
    unittest.main()
