import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    ProblemRecord,
    ProblemTicketLinkRecord,
    TicketRecord,
    UserRecord,
    get_db,
)


class ProblemListApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        created = datetime(2026, 8, 26, 12, 0)
        with self.session_factory() as db:
            db.add(UserRecord(
                id="owner",
                name="Problem Owner",
                role="agent",
                is_active=True,
            ))
            problems = [
                ProblemRecord(
                    id=f"problem-{index:03d}",
                    title=f"Recurring issue {index:03d}",
                    description="Routine root-cause investigation",
                    status=(
                        "Under Investigation" if index == 0
                        else "Known Error" if index == 1
                        else "New"
                    ),
                    assigned_to="owner",
                    created_at=created + timedelta(minutes=index),
                )
                for index in range(105)
            ]
            problems[2].title = "Literal 100%_ signal"
            problems[3].title = "Similar 100XY signal"
            db.add_all(problems)
            db.add_all([
                TicketRecord(id=f"ticket-{index}", subject=f"Ticket {index}")
                for index in range(3)
            ])
            db.flush()
            db.add_all([
                ProblemTicketLinkRecord(
                    problem_id="problem-000",
                    ticket_id=f"ticket-{index}",
                )
                for index in range(3)
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db

        current_user = UserRecord(
            id="owner",
            name="Problem Owner",
            role="agent",
            is_active=True,
        )
        main.app.dependency_overrides[main.get_current_user] = lambda: current_user
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_problem_register_is_bounded_enriched_and_constant_query_count(self):
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get("/problems")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 25)
        self.assertEqual(response.headers["x-page-limit"], "25")
        self.assertEqual(response.headers["x-page-offset"], "0")
        self.assertEqual(response.headers["x-has-more"], "true")
        self.assertEqual(response.headers["x-problem-total"], "105")
        self.assertEqual(response.headers["x-problem-investigating"], "1")
        self.assertEqual(response.headers["x-problem-known-errors"], "1")
        self.assertEqual(response.headers["x-problem-linked-tickets"], "3")
        self.assertTrue(all(row["assigned_name"] == "Problem Owner" for row in response.json()))
        self.assertLessEqual(len(statements), 5, statements)

    def test_search_is_server_side_literal_and_pages_are_stable(self):
        literal = self.client.get("/problems", params={"search": "100%_"})
        pages = [
            self.client.get("/problems", params={"limit": 50, "offset": offset})
            for offset in (0, 50, 100)
        ]

        self.assertEqual(
            [problem["id"] for problem in literal.json()],
            ["problem-002"],
        )
        self.assertEqual([len(page.json()) for page in pages], [50, 50, 5])
        ids = [problem["id"] for page in pages for problem in page.json()]
        self.assertEqual(len(ids), 105)
        self.assertEqual(len(set(ids)), 105)
        self.assertEqual(
            [page.headers["x-has-more"] for page in pages],
            ["true", "true", "false"],
        )

    def test_problem_query_validation_rejects_bad_bounds_and_nul(self):
        self.assertEqual(self.client.get("/problems", params={"limit": 101}).status_code, 422)
        self.assertEqual(self.client.get("/problems", params={"offset": -1}).status_code, 422)
        self.assertEqual(self.client.get("/problems?search=bad%00query").status_code, 422)

    def test_linked_tickets_are_bounded_stable_and_require_a_problem(self):
        with self.session_factory() as db:
            db.add_all([
                TicketRecord(
                    id=f"linked-ticket-{index:03d}",
                    subject=f"Linked ticket {index:03d}",
                    created_at=datetime(2026, 8, 27, 12, 0) + timedelta(minutes=index),
                )
                for index in range(102)
            ])
            db.flush()
            db.add_all([
                ProblemTicketLinkRecord(
                    problem_id="problem-000",
                    ticket_id=f"linked-ticket-{index:03d}",
                )
                for index in range(102)
            ])
            db.commit()

        pages = [
            self.client.get(
                "/problems/problem-000/tickets",
                params={"limit": 50, "offset": offset},
            )
            for offset in (0, 50, 100)
        ]

        self.assertTrue(all(page.status_code == 200 for page in pages))
        self.assertEqual([len(page.json()) for page in pages], [50, 50, 5])
        ticket_ids = [ticket["id"] for page in pages for ticket in page.json()]
        self.assertEqual(len(ticket_ids), 105)
        self.assertEqual(len(set(ticket_ids)), 105)
        self.assertEqual(
            [page.headers["x-has-more"] for page in pages],
            ["true", "true", "false"],
        )
        self.assertEqual(
            self.client.get("/problems/missing/tickets").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/problems/problem-000/tickets",
                params={"limit": 101},
            ).status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()
