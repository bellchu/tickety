import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    AssetRecord,
    Base,
    ProjectRecord,
    UserRecord,
    get_db,
)


class AssetProjectListApiTests(unittest.TestCase):
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
                UserRecord(id="owner-a", name="Alice Owner"),
                UserRecord(id="owner-b", name="Bob Owner"),
            ])
            db.add_all([
                AssetRecord(
                    id=f"asset-{index:03d}",
                    name="Shared asset",
                    asset_type="Hardware",
                    asset_tag=f"TAG-{index:03d}",
                    status="In Use",
                    owner_id="owner-a" if index % 2 == 0 else "owner-b",
                )
                for index in range(52)
            ])
            db.add_all([
                AssetRecord(
                    id="asset-literal",
                    name="Literal matcher",
                    asset_type="Network",
                    asset_tag="TAG_100%",
                    status="Broken",
                    owner_id="owner-a",
                    vendor="Example Networks",
                    model="NX-100",
                    location="HQ rack 1",
                ),
                AssetRecord(
                    id="asset-decoy",
                    name="Wildcard decoy",
                    asset_type="Network",
                    asset_tag="TAGX100A",
                    status="Broken",
                    owner_id="owner-b",
                ),
            ])
            db.add_all([
                ProjectRecord(
                    id=f"project-{index:03d}",
                    name="Shared project",
                    key=f"PROJECT-{index:03d}",
                    description="",
                    lead_id="owner-a" if index % 2 == 0 else "owner-b",
                    status="active",
                )
                for index in range(102)
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
            id="owner-a",
            name="Alice Owner",
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

    def test_assets_are_bounded_filtered_and_stably_paginated(self):
        default_page = self.client.get("/assets")

        self.assertEqual(default_page.status_code, 200, default_page.text)
        self.assertEqual(len(default_page.json()), 50)
        self.assertEqual(default_page.headers["x-page-limit"], "50")
        self.assertEqual(default_page.headers["x-page-offset"], "0")
        self.assertEqual(default_page.headers["x-has-more"], "true")

        first = self.client.get("/assets", params={
            "asset_type": "Hardware",
            "status": "In Use",
            "search": "Shared asset",
            "limit": 2,
            "offset": 0,
        })
        second = self.client.get("/assets", params={
            "asset_type": "Hardware",
            "status": "In Use",
            "search": "Shared asset",
            "limit": 2,
            "offset": 2,
        })

        self.assertEqual(
            [asset["id"] for asset in first.json()],
            ["asset-000", "asset-001"],
        )
        self.assertEqual(
            [asset["id"] for asset in second.json()],
            ["asset-002", "asset-003"],
        )
        self.assertEqual(second.headers["x-page-offset"], "2")
        self.assertEqual(second.headers["x-has-more"], "true")

    def test_asset_search_treats_sql_wildcards_as_literals(self):
        response = self.client.get("/assets", params={
            "asset_type": "Network",
            "status": "Broken",
            "search": "TAG_100%",
        })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([asset["id"] for asset in response.json()], ["asset-literal"])
        self.assertEqual(response.json()[0]["owner_name"], "Alice Owner")

    def test_asset_query_validation_rejects_unbounded_and_nul_inputs(self):
        for params in (
            {"limit": 0},
            {"limit": 201},
            {"offset": -1},
            {"offset": 1_000_001},
            {"asset_type": "Hard\x00ware"},
            {"status": "Act\x00ive"},
            {"search": "bad\x00search"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/assets", params=params).status_code, 422)

    def test_asset_owners_are_enriched_with_one_current_page_query(self):
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get("/assets", params={
                "asset_type": "Hardware",
                "limit": 5,
            })
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [asset["owner_name"] for asset in response.json()],
            ["Alice Owner", "Bob Owner", "Alice Owner", "Bob Owner", "Alice Owner"],
        )
        user_queries = [statement for statement in statements if "FROM users" in statement]
        self.assertEqual(len(user_queries), 1)

    def test_projects_keep_an_array_body_with_bounded_stable_pages(self):
        default_page = self.client.get("/projects")

        self.assertEqual(default_page.status_code, 200, default_page.text)
        self.assertIsInstance(default_page.json(), list)
        self.assertEqual(len(default_page.json()), 100)
        self.assertEqual(default_page.headers["x-page-limit"], "100")
        self.assertEqual(default_page.headers["x-page-offset"], "0")
        self.assertEqual(default_page.headers["x-has-more"], "true")

        next_page = self.client.get("/projects", params={"limit": 100, "offset": 100})
        self.assertEqual(
            [project["id"] for project in next_page.json()],
            ["project-100", "project-101"],
        )
        self.assertEqual(next_page.headers["x-has-more"], "false")

    def test_project_leads_are_enriched_with_one_current_page_query(self):
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get("/projects", params={"limit": 5, "offset": 1})
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [project["lead_name"] for project in response.json()],
            ["Bob Owner", "Alice Owner", "Bob Owner", "Alice Owner", "Bob Owner"],
        )
        user_queries = [statement for statement in statements if "FROM users" in statement]
        self.assertEqual(len(user_queries), 1)

    def test_project_pagination_parameters_are_validated(self):
        for params in (
            {"limit": 0},
            {"limit": 201},
            {"offset": -1},
            {"offset": 1_000_001},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/projects", params=params).status_code, 422)


if __name__ == "__main__":
    unittest.main()
