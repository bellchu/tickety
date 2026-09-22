import os
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, UserRecord, get_db, BusinessRequirementRecord, AIUsageEventRecord


class RequirementGatheringTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.user = UserRecord(id="owner", name="Owner", role="agent", is_active=True)
        with self.sessions() as db:
            db.add_all([self.user, UserRecord(id="other", name="Other", role="agent", is_active=True)])
            db.commit()
            db.refresh(self.user)
            db.expunge(self.user)

        def get_session():
            with self.sessions() as db:
                yield db

        self.previous_overrides = dict(main.app.dependency_overrides)
        main.app.dependency_overrides[get_db] = get_session
        main.app.dependency_overrides[main.get_authenticated_user] = lambda: self.user
        self.environment = patch.dict(os.environ, {"APP_MODE": "demo", "LOGIN_REQUIRED": "false", "CORS_ALLOW_ORIGINS": "http://testserver"})
        self.environment.start()
        self.client = TestClient(main.app)
        self.path = "/requirements"

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(self.previous_overrides)
        self.environment.stop()
        self.engine.dispose()

    def workspace(self):
        response = self.client.post(self.path, json={"title": "Invoice intake", "objective": "Reduce invoice review delays."})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def source(self, workspace):
        response = self.client.post(f"{self.path}/{workspace}/sources", json={"title": "Operations SOP", "kind": "sop", "content": "Every invoice must receive an acknowledgement within 30 seconds."})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def payload(self, source):
        return {"source_id": source, "title": "Acknowledge receipt", "actor": "finance analyst", "action": "receive an invoice acknowledgement", "benefit": "I can confirm successful submission", "evidence_quote": "Every invoice must receive an acknowledgement within 30 seconds.", "acceptance_criteria": ["Given a valid invoice, when submitted, then acknowledgement appears within 30 seconds."], "priority": "must"}

    def test_complete_workflow_and_edit_invalidates_validation_and_story(self):
        workspace = self.workspace()
        source = self.source(workspace)
        response = self.client.post(f"{self.path}/{workspace}/items", json=self.payload(source))
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        self.assertEqual(row["reference"], "REQ-001")
        item = f"{self.path}/{workspace}/items/{row['id']}"
        self.assertEqual(self.client.post(item + "/validate", json={"revision": 1}).status_code, 422)
        self.assertEqual(self.client.post(item + "/story", json={"revision": 1}).status_code, 409)
        row = self.client.post(item + "/validate", json={"revision": 1, "reviewer_role": "Product Owner", "validation_note": "Reviewed against the operations SOP."}).json()
        self.assertEqual(row["validated_by"], "owner")
        row = self.client.post(item + "/story", json={"revision": row["revision"]}).json()
        self.assertIn("As a finance analyst", row["story"]["statement"])
        self.assertEqual(row["story"]["source_id"], source)
        self.assertEqual(row["story"]["requirement_reference"], "REQ-001")
        self.assertEqual(row["story"]["reference"], "US-001")
        self.assertEqual(self.client.post(item + "/validate", json={"revision": row["revision"], "reviewer_role": "DTL", "validation_note": "Attempt to overwrite the review."}).status_code, 409)
        response = self.client.put(item, json={**self.payload(source), "revision": row["revision"], "benefit": "I can track the queue"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "draft")
        self.assertIsNone(response.json()["validated_at"])
        self.assertIsNone(response.json()["story"])

    def test_source_and_workspace_boundaries(self):
        workspace = self.workspace()
        source = self.source(workspace)
        other_workspace = self.workspace()
        response = self.client.post(f"{self.path}/{other_workspace}/items", json=self.payload(source))
        self.assertEqual(response.status_code, 422)
        self.user.id = "other"
        for suffix in ("", f"/sources/{source}"):
            self.assertEqual(self.client.get(f"{self.path}/{workspace}{suffix}").status_code, 404)
        self.assertEqual(self.client.get(self.path).json()["items"], [])
        self.assertEqual(self.client.post(f"{self.path}/{workspace}/items", json=self.payload(source)).status_code, 404)

    def test_unverified_quote_is_rejected(self):
        workspace = self.workspace()
        source = self.source(workspace)
        response = self.client.post(f"{self.path}/{workspace}/items", json={**self.payload(source), "evidence_quote": "Invented source evidence."})
        self.assertEqual(response.status_code, 422)

    def test_stale_revision_cannot_overwrite_or_validate(self):
        workspace = self.workspace()
        source = self.source(workspace)
        row = self.client.post(f"{self.path}/{workspace}/items", json=self.payload(source)).json()
        item = f"{self.path}/{workspace}/items/{row['id']}"
        self.assertEqual(self.client.put(item, json={**self.payload(source), "revision": 1}).status_code, 200)
        self.assertEqual(self.client.put(item, json={**self.payload(source), "revision": 1}).status_code, 409)
        self.assertEqual(self.client.post(item + "/validate", json={"revision": 1, "reviewer_role": "Product Owner", "validation_note": "Reviewed against the operations SOP."}).status_code, 409)

    def test_incomplete_or_vague_requirement_cannot_be_validated(self):
        workspace = self.workspace()
        source = self.source(workspace)
        row = self.client.post(f"{self.path}/{workspace}/items", json={**self.payload(source), "actor": "", "action": "process invoices fast", "acceptance_criteria": []}).json()
        self.assertEqual(len(row["quality_issues"]), 3)
        response = self.client.post(f"{self.path}/{workspace}/items/{row['id']}/validate", json={"revision": 1, "reviewer_role": "Product Owner", "validation_note": "Reviewed against the operations SOP."})
        self.assertEqual(response.status_code, 422)

    def test_unknown_roles_cannot_access_workspaces(self):
        self.user.role = "requester"
        self.assertEqual(self.client.get(self.path).status_code, 403)

    def test_anonymous_demo_cannot_access_workspaces(self):
        del main.app.dependency_overrides[main.get_authenticated_user]
        with patch.object(main, "_resolve_request_user", return_value=None):
            self.assertEqual(self.client.get(self.path).status_code, 401)

    def test_bounds_and_control_characters(self):
        self.assertEqual(self.client.get(self.path + "?limit=101").status_code, 422)
        self.assertEqual(self.client.post(self.path, json={"title": "\x00", "objective": "A business objective"}).status_code, 422)
        workspace = self.workspace()
        self.assertEqual(self.client.post(f"{self.path}/{workspace}/sources", json={"title": "Too big", "kind": "document", "content": "x" * 100001}).status_code, 422)

    def ai_manager(self, result):
        return SimpleNamespace(is_mock=False, prompt_char_limit=4000, model_name="test/configured-provider", analyze=AsyncMock(return_value=result))

    def test_ai_gather_suggestions_are_grounded_and_never_saved_automatically(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        candidate = {key: value for key, value in self.payload(source).items() if key != "source_id"}
        candidate["assumptions"] = []
        manager = self.ai_manager({"candidates": [candidate, {**candidate, "evidence_quote": "This quote is not in the source."}], "questions": ["Who owns the acknowledgement process?"]})
        with patch.object(main, "llm_mgr", manager):
            response = self.client.post(f"{self.path}/{workspace}/sources/{source}/gather", headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["candidates"]), 1)
        self.assertEqual(response.json()["discarded_candidates"], 1)
        with self.sessions() as db:
            self.assertEqual(db.query(BusinessRequirementRecord).count(), 0)
            self.assertEqual(db.query(AIUsageEventRecord).filter_by(task="requirements_gather").count(), 1)

    def test_ai_requires_explicit_origin_and_demo_admin(self):
        workspace = self.workspace()
        source = self.source(workspace)
        manager = self.ai_manager({})
        endpoint = f"{self.path}/{workspace}/sources/{source}/gather"
        with patch.object(main, "llm_mgr", manager):
            self.assertEqual(self.client.post(endpoint, headers={"Origin": "http://testserver"}).status_code, 403)
            self.user.role = "admin"
            self.assertEqual(self.client.post(endpoint).status_code, 403)
            self.assertEqual(self.client.post(endpoint, headers={"Origin": "https://attacker.example"}).status_code, 403)
        manager.analyze.assert_not_called()

    def test_unconfigured_ai_never_returns_synthetic_suggestions(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        manager = self.ai_manager({})
        manager.is_mock = True
        with patch.object(main, "llm_mgr", manager):
            response = self.client.post(f"{self.path}/{workspace}/sources/{source}/gather", headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 503)
        manager.analyze.assert_not_called()

    def test_ai_review_cannot_sign_off_or_change_a_requirement(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        row = self.client.post(f"{self.path}/{workspace}/items", json=self.payload(source)).json()
        manager = self.ai_manager({"findings": [{"category": "missing_context", "finding": "Failure handling is unspecified.", "question": "What should happen if delivery fails?"}], "questions": []})
        endpoint = f"{self.path}/{workspace}/items/{row['id']}/assist"
        with patch.object(main, "llm_mgr", manager):
            response = self.client.post(endpoint, headers={"Origin": "http://testserver"}, json={"mode": "review", "revision": 1})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.post(endpoint, headers={"Origin": "http://testserver"}, json={"mode": "story", "revision": 1}).status_code, 409)
        current = self.client.get(f"{self.path}/{workspace}").json()["requirements"][0]
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current["status"], "draft")
        self.assertIsNone(current["story"])
        manager.analyze.assert_awaited_once()

    def test_ai_prompt_redacts_sensitive_data_and_reports_partial_sources(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.client.post(f"{self.path}/{workspace}/sources", json={"title": "Email", "kind": "email", "content": "Contact person@example.com. password=do-not-share\n" + "business context " * 1000}).json()["id"]
        manager = self.ai_manager({"candidates": [], "questions": []})
        with patch.object(main, "llm_mgr", manager):
            response = self.client.post(f"{self.path}/{workspace}/sources/{source}/gather", headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["source_truncated"])
        prompt = manager.analyze.call_args.args[0]
        self.assertLessEqual(len(prompt), 4000)
        self.assertNotIn("person@example.com", prompt)
        self.assertNotIn("do-not-share", prompt)
        self.assertIn("content", json.loads(prompt))

    def test_ai_budget_denial_prevents_provider_dispatch(self):
        from fastapi import HTTPException
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        manager = self.ai_manager({})
        with patch.object(main, "llm_mgr", manager), patch.object(main, "_reserve_ai_request", side_effect=HTTPException(429, "ai_daily_budget_exceeded")):
            response = self.client.post(f"{self.path}/{workspace}/sources/{source}/gather", headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 429)
        manager.analyze.assert_not_called()

    def test_workspace_overview_does_not_load_document_bodies(self):
        workspace = self.workspace()
        self.source(workspace)
        statements = []
        def record(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", record)
        try:
            response = self.client.get(f"{self.path}/{workspace}")
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        self.assertEqual(response.status_code, 200)
        source_queries = [sql for sql in statements if "FROM requirement_sources" in sql]
        self.assertEqual(len(source_queries), 1)
        self.assertNotIn("requirement_sources.content AS", source_queries[0])
        self.assertNotIn("content", response.json()["sources"][0])

    def test_ai_malformed_output_is_rejected_without_saving(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        manager = self.ai_manager({"approved": True, "candidates": [], "questions": []})
        with patch.object(main, "llm_mgr", manager):
            response = self.client.post(f"{self.path}/{workspace}/sources/{source}/gather", headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "invalid_ai_output")


if __name__ == "__main__":
    unittest.main()
