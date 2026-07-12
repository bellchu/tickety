import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    ServiceItemRecord,
    ServiceRequestRecord,
    TicketRecord,
    get_db,
)


class ServiceRequestApiTests(unittest.TestCase):
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
                TicketRecord(id="ticket-1", subject="Laptop request"),
                TicketRecord(id="ticket-2", subject="Access request"),
                ServiceItemRecord(id="service-1", name="Managed laptop"),
                ServiceItemRecord(id="service-2", name="Application access"),
                ServiceRequestRecord(id="request-1", ticket_id="ticket-1", service_item_id="service-1"),
                ServiceRequestRecord(id="request-2", ticket_id="ticket-2", service_item_id="service-2"),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_service_names_are_enriched_with_one_batched_query(self):
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get("/service-requests")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(response.status_code, 200)
        by_id = {request["id"]: request for request in response.json()}
        self.assertEqual(by_id["request-1"]["service_name"], "Managed laptop")
        self.assertEqual(by_id["request-2"]["service_name"], "Application access")
        service_queries = [statement for statement in statements if "FROM service_items" in statement]
        self.assertEqual(len(service_queries), 1)


if __name__ == "__main__":
    unittest.main()
