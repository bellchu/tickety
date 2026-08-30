import hashlib
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, TicketRecord, get_db


class PortalSecurityTests(unittest.TestCase):
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
        self.auth_middleware_patch = patch.object(
            main,
            "_auth_required_for_request",
            return_value=False,
        )
        self.auth_middleware_patch.start()
        self.demo_ticketing_patch = patch.object(
            main.settings_module,
            "is_production_mode",
            return_value=False,
        )
        self.demo_ticketing_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.demo_ticketing_patch.stop()
        self.auth_middleware_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _create_ticket(self):
        return self.client.post(
            "/portal/tickets",
            json={
                "subject": "Cannot connect to VPN",
                "description": "The client times out.",
                "reporter": "Requester@Example.com",
                "priority": "high",
            },
        )

    def test_create_issues_one_time_capability_and_stores_only_hash(self):
        response = self._create_ticket()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        token = body["access_token"]
        self.assertGreaterEqual(len(token), 43)
        self.assertIn(f"/portal#token={token}", body["tracking_url"])
        self.assertNotIn("?token=", body["tracking_url"])
        self.assertNotIn("reporter", body)
        self.assertTrue(body["id"].startswith("portal-"))
        self.assertEqual(len(body["id"]), len("portal-") + 32)

        with self.session_factory() as db:
            ticket = db.get(TicketRecord, body["id"])
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket.reporter, "requester@example.com")
            self.assertNotEqual(ticket.portal_access_token_hash, token)
            self.assertEqual(
                ticket.portal_access_token_hash,
                hashlib.sha256(token.encode("ascii")).hexdigest(),
            )
            self.assertGreater(ticket.portal_access_expires_at, datetime.utcnow())

    def test_valid_capability_returns_ticket_without_reporter_or_token(self):
        created = self._create_ticket().json()

        response = self.client.get(
            "/portal/tickets",
            headers={"Authorization": f"Bearer {created['access_token']}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["id"], created["id"])
        self.assertNotIn("reporter", response.json())
        self.assertNotIn("access_token", response.json())
        self.assertNotIn("tracking_url", response.json())

    def test_invalid_missing_and_legacy_lookups_have_same_non_enumerating_response(self):
        created = self._create_ticket().json()
        token = created["access_token"]
        invalid_tokens = [token[:-1] + ("A" if token[-1] != "A" else "B"), "A" * 43]

        responses = [
            self.client.get("/portal/tickets"),
            self.client.get(
                "/portal/tickets",
                params={"reporter": "requester@example.com", "ticket_id": created["id"]},
            ),
            # Query-string capability transport is deliberately unsupported so
            # secrets cannot leak through request targets and access logs.
            self.client.get("/portal/tickets", params={"access_token": token}),
            self.client.get("/portal/tickets", headers={"Authorization": f"Basic {token}"}),
            self.client.get("/portal/tickets", headers={"Authorization": f"Bearer  {token}"}),
            *(self.client.get(
                "/portal/tickets",
                headers={"Authorization": f"Bearer {value}"},
            ) for value in invalid_tokens),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "Tracking link is invalid or expired"})
            self.assertNotIn(created["id"], response.text)

    def test_expired_capability_uses_same_non_enumerating_response(self):
        created = self._create_ticket().json()
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, created["id"])
            ticket.portal_access_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

        response = self.client.get(
            "/portal/tickets",
            headers={"Authorization": f"Bearer {created['access_token']}"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Tracking link is invalid or expired"})


if __name__ == "__main__":
    unittest.main()
