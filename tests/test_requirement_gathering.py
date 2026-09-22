import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import Base, UserRecord, get_db


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
        self.environment = patch.dict(os.environ, {"APP_MODE": "demo", "LOGIN_REQUIRED": "false"})
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


if __name__ == "__main__":
    unittest.main()
