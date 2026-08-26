import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, get_db


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_liveness_does_not_require_database(self):
        def unavailable_db():
            raise AssertionError("liveness must not resolve the database dependency")
            yield

        main.app.dependency_overrides[get_db] = unavailable_db

        response = self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "alive"})

    def test_readiness_succeeds_when_database_is_available(self):
        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready", "checks": {"database": "ok"}})

    def test_readiness_fails_safely_without_leaking_database_error(self):
        class UnavailableDatabase:
            def execute(self, _statement):
                raise RuntimeError("postgresql://user:secret@private-db/tickety")

        def unavailable_db():
            yield UnavailableDatabase()

        main.app.dependency_overrides[get_db] = unavailable_db

        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"status": "not_ready", "checks": {"database": "unavailable"}},
        )
        self.assertNotIn("secret", response.text)
        self.assertNotIn("private-db", response.text)

    def test_legacy_health_contract_remains_available(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_api_and_version_expose_the_rebranded_product_name(self):
        self.assertEqual(main.app.title, "Tickety OPS Tower")
        response = self.client.get("/version")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["app"], "Tickety OPS Tower")

    def test_all_health_routes_are_public_in_production_auth_mode(self):
        with patch.object(main, "_auth_required_for_request", return_value=True):
            for path in ("/health", "/health/live", "/health/ready"):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertNotEqual(response.status_code, 401)
                    self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
