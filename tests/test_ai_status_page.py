import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    LLMCallRecord,
    LLMProviderCooldownRecord,
    SessionRecord,
    SyncStateRecord,
    TicketRecord,
    UserRecord,
    get_db,
)


class AIStatusPageApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.now = datetime.utcnow().replace(microsecond=0)
        with self.session_factory() as db:
            db.add_all([
                UserRecord(
                    id="status-admin",
                    name="Status Admin",
                    role="admin",
                    is_active=True,
                ),
                UserRecord(
                    id="status-agent",
                    name="Status Agent",
                    role="agent",
                    is_active=True,
                ),
                SessionRecord(
                    token="status-admin-session",
                    user_id="status-admin",
                    expires_at=self.now + timedelta(hours=1),
                ),
                SessionRecord(
                    token="status-agent-session",
                    user_id="status-agent",
                    expires_at=self.now + timedelta(hours=1),
                ),
            ])
            db.add_all([
                TicketRecord(id="not-analyzed", subject="No AI task", ai_status=None),
                TicketRecord(
                    id="queued-ready",
                    subject="Ready queue item",
                    ai_status="queued",
                    ai_requested_artifacts="triage,summary,untrusted-artifact",
                    ai_attempts=1,
                    updated_at=self.now - timedelta(minutes=30),
                ),
                TicketRecord(
                    id="queued-retry",
                    subject="Capacity retry",
                    ai_status="queued",
                    ai_requested_artifacts="resolution",
                    ai_next_attempt_at=self.now + timedelta(minutes=5),
                    ai_error="resolution:provider_capacity",
                ),
                TicketRecord(
                    id="running-active",
                    subject="Active analysis",
                    ai_status="running",
                    ai_started_at=self.now - timedelta(seconds=20),
                    ai_lease_expires_at=self.now + timedelta(minutes=2),
                ),
                TicketRecord(
                    id="running-expired",
                    subject="Interrupted analysis",
                    ai_status="running",
                    ai_started_at=self.now - timedelta(minutes=10),
                    ai_lease_expires_at=self.now - timedelta(minutes=5),
                ),
                TicketRecord(
                    id="complete",
                    subject="Full analysis complete",
                    ai_status="completed",
                    ai_model="foundry/deployment-a",
                    ai_generated_at=self.now - timedelta(hours=1),
                ),
                TicketRecord(
                    id="triage-complete",
                    subject="Triage complete",
                    ai_status="triage_completed",
                    ai_generated_at=self.now - timedelta(hours=2),
                ),
                TicketRecord(
                    id="partial",
                    subject="Partial artifacts",
                    ai_status="partial",
                    ai_error="summary:timeout",
                ),
                TicketRecord(
                    id="stale",
                    subject="Changed ticket",
                    ai_status="legacy_stale",
                ),
                TicketRecord(
                    id="dead-letter",
                    subject="Retries exhausted",
                    ai_status="dead_letter",
                    ai_attempts=3,
                    ai_error="provider token=sk-proj-abcdefghijklmnopqrst failed",
                ),
                TicketRecord(
                    id="closed-paused",
                    subject="Historical closed task",
                    status="Closed",
                    ai_status="paused",
                    ai_error="automatic_scope_excluded",
                ),
            ])
            db.add(SyncStateRecord(
                binding_id="binding-status",
                provider="freshservice",
                last_status="error",
                last_error="sync_failed:RuntimeError",
                run_finished_at=self.now - timedelta(minutes=1),
            ))
            db.add_all([
                LLMCallRecord(
                    provider="foundry",
                    model="deployment-a",
                    task="TriageAnalysis",
                    status="success",
                    attempts=1,
                    latency_ms=420,
                    total_tokens=120,
                    created_at=self.now - timedelta(minutes=3),
                ),
                LLMCallRecord(
                    provider="foundry",
                    model="deployment-a",
                    task="TicketSummary",
                    status="attempt_failed",
                    attempts=2,
                    latency_ms=800,
                    total_tokens=40,
                    error_code="provider_capacity",
                    created_at=self.now - timedelta(minutes=2),
                ),
                LLMCallRecord(
                    provider="foundry",
                    model="deployment-a",
                    task="TicketResolution",
                    status="capacity_deferred",
                    attempts=1,
                    latency_ms=5,
                    total_tokens=0,
                    error_code="provider_capacity",
                    created_at=self.now - timedelta(minutes=1),
                ),
                LLMProviderCooldownRecord(
                    provider="foundry",
                    reason="reserved_tokens_day_exhausted",
                    retry_at=self.now + timedelta(hours=2),
                    updated_at=self.now,
                ),
            ])
            db.commit()

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
        self.production_mode_patch = patch.object(
            main.settings_module,
            "is_production_mode",
            return_value=False,
        )
        self.production_mode_patch.start()
        self.session_local_patch = patch.object(main, "SessionLocal", self.session_factory)
        self.session_local_patch.start()
        self.client = TestClient(main.app)
        self.client.cookies.set(main.SESSION_COOKIE, "status-admin-session")
        self.headers = {"Origin": "http://testserver"}

    def tearDown(self):
        self.session_local_patch.stop()
        self.production_mode_patch.stop()
        self.auth_middleware_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_status_combines_queue_health_tasks_and_prompt_free_call_telemetry(self):
        with patch.object(
            main.settings_module,
            "automation_enabled",
            side_effect=lambda key, *_args: key == "AUTO_TRIAGE_ENABLED",
        ):
            response = self.client.get("/admin/settings/ai-status", headers=self.headers)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["queue"]["total_tickets"], 11)
        self.assertEqual(payload["queue"]["not_analyzed"], 1)
        self.assertEqual(payload["queue"]["not_applicable"], 1)
        self.assertEqual(payload["queue"]["queued"], 2)
        self.assertEqual(payload["queue"]["queued_ready"], 1)
        self.assertEqual(payload["queue"]["retry_scheduled"], 1)
        self.assertEqual(payload["queue"]["running_active"], 1)
        self.assertEqual(payload["queue"]["lease_expired"], 1)
        self.assertEqual(payload["queue"]["completed"], 2)
        self.assertEqual(payload["queue"]["attention"], 4)
        self.assertIsInstance(payload["active_routing_backlog_enabled"], bool)
        self.assertEqual(payload["total_tasks"], 11)

        tasks = {task["ticket_id"]: task for task in payload["tasks"]}
        self.assertEqual(tasks["queued-retry"]["lifecycle"], "retry_scheduled")
        self.assertEqual(tasks["running-active"]["lifecycle"], "running")
        self.assertEqual(tasks["running-expired"]["lifecycle"], "lease_expired")
        self.assertEqual(tasks["triage-complete"]["lifecycle"], "completed")
        self.assertEqual(tasks["closed-paused"]["lifecycle"], "not_applicable")
        self.assertEqual(
            tasks["queued-ready"]["requested_artifacts"],
            ["summary", "triage"],
        )
        self.assertEqual(tasks["dead-letter"]["error_code"], "legacy_error")
        self.assertNotIn("sk-proj-abcdefghijklmnopqrst", response.text)

        self.assertEqual(payload["calls_24h"]["calls"], 3)
        self.assertEqual(payload["calls_24h"]["successful"], 1)
        self.assertEqual(payload["calls_24h"]["failed_attempts"], 1)
        self.assertEqual(payload["calls_24h"]["deferred"], 1)
        self.assertEqual(payload["calls_24h"]["total_tokens"], 160)
        self.assertEqual(len(payload["recent_calls"]), 2)
        self.assertEqual(payload["provider_cooldown"]["provider"], "foundry")
        self.assertEqual(
            payload["provider_cooldown"]["reason"],
            "reserved_tokens_day_exhausted",
        )
        self.assertEqual(
            [feature["enabled"] for feature in payload["automation"]],
            [True, False, False, False, False],
        )

    def test_admin_can_explicitly_reveal_bounded_redacted_diagnostics(self):
        partial = self.client.get(
            "/admin/settings/ai-status/partial/diagnostics",
            headers=self.headers,
        )
        self.assertEqual(partial.status_code, 200, partial.text)
        self.assertEqual(partial.headers["cache-control"], "no-store")
        self.assertEqual(partial.json()["entries"][0]["message"], "summary:timeout")

        secret = self.client.get(
            "/admin/settings/ai-status/dead-letter/diagnostics",
            headers=self.headers,
        )
        self.assertEqual(secret.status_code, 200, secret.text)
        self.assertIn("[secret]", secret.json()["entries"][0]["message"])
        self.assertNotIn("sk-proj-abcdefghijklmnopqrst", secret.text)

        sync = self.client.get(
            "/admin/settings/status/diagnostics",
            params={"area": "sync"},
            headers=self.headers,
        )
        self.assertEqual(sync.status_code, 200, sync.text)
        self.assertEqual(sync.json()["entries"][0]["message"], "sync_failed:RuntimeError")

        ai = self.client.get(
            "/admin/settings/status/diagnostics",
            params={"area": "ai"},
            headers=self.headers,
        )
        self.assertEqual(ai.status_code, 200, ai.text)
        self.assertTrue(ai.json()["entries"])
        self.assertNotIn("sk-proj-abcdefghijklmnopqrst", ai.text)
        self.assertNotIn("capacity_deferred", ai.text)

    def test_ai_diagnostics_only_show_current_unresolved_provider_outcomes(self):
        with self.session_factory() as db:
            db.add_all([
                LLMCallRecord(
                    provider="foundry",
                    model="deployment-a",
                    task="TicketSummary",
                    status="success",
                    attempts=3,
                    created_at=self.now - timedelta(minutes=1),
                ),
                LLMCallRecord(
                    provider="custom",
                    model="retired-model",
                    task="TriageAnalysis",
                    status="attempt_failed",
                    attempts=1,
                    error_code="provider_unavailable",
                    created_at=self.now,
                ),
                LLMCallRecord(
                    provider="foundry",
                    model="deployment-a",
                    task="ResolutionAnalysis",
                    status="attempt_failed",
                    attempts=1,
                    error_code="timeout",
                    created_at=self.now,
                ),
            ])
            db.commit()

        with patch.object(main.engine, "llm", SimpleNamespace(provider="foundry")):
            response = self.client.get(
                "/admin/settings/status/diagnostics",
                params={"area": "ai"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        sources = [entry["source"] for entry in response.json()["entries"]]
        self.assertIn("llm:foundry:ResolutionAnalysis", sources)
        self.assertNotIn("llm:foundry:TicketSummary", sources)
        self.assertFalse(any(source.startswith("llm:custom:") for source in sources))

    def test_operational_views_and_search_are_bounded_server_side(self):
        attention = self.client.get(
            "/admin/settings/ai-status",
            params={"view": "attention", "limit": 2},
            headers=self.headers,
        )
        self.assertEqual(attention.status_code, 200, attention.text)
        self.assertEqual(attention.json()["total_tasks"], 4)
        self.assertEqual(len(attention.json()["tasks"]), 2)

        active = self.client.get(
            "/admin/settings/ai-status",
            params={"view": "active", "search": "Capacity retry"},
            headers=self.headers,
        )
        self.assertEqual(active.status_code, 200, active.text)
        self.assertEqual(active.json()["total_tasks"], 1)
        self.assertEqual(active.json()["tasks"][0]["ticket_id"], "queued-retry")

        historical = self.client.get(
            "/admin/settings/ai-status",
            params={"view": "not_applicable"},
            headers=self.headers,
        )
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(historical.json()["total_tasks"], 1)
        self.assertEqual(
            historical.json()["tasks"][0]["lifecycle"], "not_applicable"
        )

        for params in ({"view": "arbitrary"}, {"limit": 101}, {"offset": -1}):
            with self.subTest(params=params):
                self.assertEqual(
                    self.client.get(
                        "/admin/settings/ai-status",
                        params=params,
                        headers=self.headers,
                    ).status_code,
                    422,
                )

    def test_status_requires_an_administrator(self):
        self.client.cookies.set(main.SESSION_COOKIE, "status-agent-session")

        response = self.client.get("/admin/settings/ai-status", headers=self.headers)

        self.assertEqual(response.status_code, 403)
        diagnostic = self.client.get(
            "/admin/settings/status/diagnostics",
            params={"area": "ai"},
            headers=self.headers,
        )
        self.assertEqual(diagnostic.status_code, 403)


if __name__ == "__main__":
    unittest.main()
