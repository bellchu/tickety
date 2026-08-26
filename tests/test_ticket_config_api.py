import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, TicketPriorityConfigRecord, UserRecord, get_db


class TicketConfigApiTests(unittest.TestCase):
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
                UserRecord(id="agent", name="Agent", role="agent", is_active=True),
            ])
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.current_role = "admin"

        def current_user():
            with self.session_factory() as db:
                return db.get(UserRecord, self.current_role)

        main.app.dependency_overrides[main.get_current_user] = current_user
        main.app.dependency_overrides[main.get_authenticated_user] = current_user
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=False)
        self.auth_patch.start()
        self.roles_patch = patch.object(main, "_roles_required_for_request", return_value=None)
        self.roles_patch.start()
        self.production_patch = patch.object(main.settings_module, "is_production_mode", return_value=False)
        self.production_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.production_patch.stop()
        self.roles_patch.stop()
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_agent_can_read_options_but_cannot_mutate_configuration(self):
        self.current_role = "agent"

        self.assertEqual(self.client.get("/config/statuses").status_code, 200)
        self.assertEqual(self.client.get("/config/priorities").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/config/statuses",
                json={"name": "Waiting", "label": "Waiting"},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/config/notifications").status_code, 403)

    def test_status_input_is_normalized_and_lifecycle_is_consistent(self):
        created = self.client.post(
            "/config/statuses",
            json={
                "name": "  Waiting for vendor  ",
                "label": "  Waiting for vendor  ",
                "color": "amber",
                "is_open": True,
                "is_terminal": False,
                "sort_order": 8,
            },
        )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["name"], "Waiting for vendor")
        self.assertEqual(
            self.client.post(
                "/config/statuses",
                json={"name": "waiting FOR vendor", "label": "Duplicate"},
            ).status_code,
            409,
        )
        contradictory = self.client.post(
            "/config/statuses",
            json={
                "name": "Impossible",
                "label": "Impossible",
                "is_open": True,
                "is_terminal": True,
            },
        )
        self.assertEqual(contradictory.status_code, 422)

    def test_priority_bounds_and_supported_colors_are_enforced(self):
        valid = self.client.post(
            "/config/priorities",
            json={
                "name": "P0",
                "label": "立即处理",
                "color": "red",
                "sla_hours": 1,
                "weight": 1,
                "sort_order": 0,
            },
        )
        self.assertEqual(valid.status_code, 201, valid.text)
        self.assertEqual(valid.json()["label"], "立即处理")

        for payload in (
            {"name": "No weight", "label": "No weight", "weight": 0},
            {"name": "Too long", "label": "Too long", "sla_hours": 8_761},
            {"name": "Unknown color", "label": "Unknown color", "color": "magenta"},
            {"name": "ÉLEVÉ", "label": "Localized label is allowed"},
            {"name": "x" * 33, "label": "Too long to use on a ticket"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post("/config/priorities", json=payload).status_code,
                    422,
                )

        nul_label = self.client.post(
            "/config/priorities",
            json={"name": "Safe key", "label": "invalid\u0000label"},
        )
        self.assertEqual(nul_label.status_code, 422, nul_label.text)

    def test_priority_sla_uses_the_same_normalized_identity_as_queue_ordering(self):
        with self.session_factory() as db:
            db.add(TicketPriorityConfigRecord(
                name="Case Mix",
                name_key="case mix",
                label="Mixed case",
                sla_hours=2,
                weight=3,
            ))
            db.commit()
            self.assertEqual(main._priority_sla_hours(db, " case MIX "), 2)

        with self.session_factory() as db:
            self.assertEqual(main._priority_sla_hours(db, " p1 "), 4)


if __name__ == "__main__":
    unittest.main()
