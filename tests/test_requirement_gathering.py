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

    def test_repeated_requirement_capture_preserves_signed_story_and_history(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}"
        payload = self.payload(source)
        row = self.client.post(base + "/items", json=payload).json()
        route = base + "/items/" + row["id"]
        signed = self.client.post(route + "/validate", json={"revision": 1, "reviewer_role": "Product Owner", "validation_note": "Confirmed the agreed acknowledgement."}).json()
        story = self.client.post(route + "/story", json={"revision": signed["revision"]}).json()
        history = self.client.get(route + "/history").json()
        duplicate = self.client.post(base + "/items", json={**payload, "title": "  " + payload["title"] + "  "})
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertTrue(duplicate.json()["reused"])
        self.assertEqual({key: value for key, value in duplicate.json().items() if key != "reused"}, story)
        self.assertEqual(self.client.get(route + "/history").json(), history)
        self.assertEqual(len(self.client.get(base).json()["requirements"]), 1)

    def test_requirement_reuse_requires_identical_business_fields_and_scope(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}/items"
        payload = self.payload(source)
        self.assertEqual(self.client.post(base, json=payload).status_code, 201)
        changes = {"title": "Track intake", "actor": "Procurement analyst", "action": "receive a reference number",
                   "benefit": "I can track intake", "priority": "could", "evidence_quote": "acknowledgement within 30 seconds.",
                   "acceptance_criteria": ["Given an invoice, confirm receipt within twenty seconds."]}
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertEqual(self.client.post(base, json={**payload, field: value}).status_code, 201)
        other = self.workspace()
        other_source = self.source(other)
        self.assertEqual(self.client.post(f"{self.path}/{other}/items", json=self.payload(other_source)).status_code, 201)
        self.user.id = "other"
        self.assertEqual(self.client.post(base, json=payload).status_code, 404)

    def test_requirement_reuse_at_capacity_does_not_consume_another_reference(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}/items"
        payload = self.payload(source)
        first = self.client.post(base, json=payload).json()
        values = dict(payload)
        criteria = values.pop("acceptance_criteria")
        with self.sessions() as db:
            db.add_all([BusinessRequirementRecord(id=f"capacity-{i}", workspace_id=workspace, number=i + 1,
                        acceptance_json=json.dumps(criteria), **{**values, "title": f"Requirement {i}"}) for i in range(1, 200)])
            db.commit()
        duplicate = self.client.post(base, json=payload)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()["id"], first["id"])
        self.assertEqual(self.client.post(base, json={**payload, "title": "Another requirement"}).status_code, 409)

    def test_unchanged_edit_preserves_draft_and_signed_agreement(self):
        workspace = self.workspace()
        source = self.source(workspace)
        payload = self.payload(source)
        row = self.client.post(f"{self.path}/{workspace}/items", json=payload).json()
        route = f"{self.path}/{workspace}/items/{row['id']}"
        for signed in (False, True):
            if signed:
                row = self.client.post(route + "/validate", json={"revision": row["revision"], "reviewer_role": "Product Owner", "validation_note": "Confirmed with the operations owner."}).json()
                row = self.client.post(route + "/story", json={"revision": row["revision"]}).json()
            history = self.client.get(route + "/history").json()
            response = self.client.put(route, json={**payload, "title": " " + payload["title"] + " ", "revision": row["revision"]})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertTrue(result.pop("unchanged"))
            self.assertEqual(result, row)
            self.assertEqual(self.client.get(route + "/history").json(), history)
        self.assertEqual(self.client.put(route, json={**payload, "revision": 1}).status_code, 409)
        changed = self.client.put(route, json={**payload, "acceptance_criteria": ["Given an invoice, confirm receipt within twenty seconds."], "revision": row["revision"]}).json()
        self.assertEqual(changed["revision"], row["revision"] + 1)
        self.assertEqual(changed["status"], "draft")
        self.assertIsNone(changed["story"])

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
        self.assertEqual(self.client.put(item, json={**self.payload(source), "revision": 1, "benefit": "Track processing outcomes"}).status_code, 200)
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

    def test_blocking_question_invalidates_only_affected_agreement_and_needs_new_signoff(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}"
        item = self.client.post(base + "/items", json=self.payload(source)).json()
        other = self.client.post(base + "/items", json={**self.payload(source), "title": "Track missing invoices"}).json()
        route = base + "/items/" + item["id"]
        signed = self.client.post(route + "/validate", json={"revision": 1, "reviewer_role": "Product Owner", "validation_note": "Confirmed the business need."}).json()
        self.client.post(route + "/story", json={"revision": signed["revision"]})
        response = self.client.post(base + "/decisions", json={"requirement_id": item["id"], "question": "Who handles acknowledgement failures?", "owner_role": "Operations lead"})
        self.assertEqual(response.status_code, 201, response.text)
        decision = response.json()
        detail = self.client.get(base).json()
        changed = next(row for row in detail["requirements"] if row["id"] == item["id"])
        unchanged = next(row for row in detail["requirements"] if row["id"] == other["id"])
        self.assertEqual(unchanged["revision"], 1)
        self.assertEqual(changed["status"], "draft")
        self.assertIsNone(changed["story"])
        review = {"revision": changed["revision"], "reviewer_role": "Product Owner", "validation_note": "Confirmed the business need."}
        self.assertEqual(self.client.post(route + "/validate", json=review).status_code, 409)
        resolved = self.client.post(base + "/decisions/" + decision["id"] + "/resolve", json={"resolution": "Operations lead monitors failures and retries within five minutes."})
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["resolved_by"], "owner")
        self.assertIsNotNone(resolved.json()["resolved_at"])
        self.assertEqual(self.client.post(route + "/story", json={"revision": changed["revision"]}).status_code, 409)
        self.assertEqual(self.client.post(route + "/validate", json=review).status_code, 200)
        self.assertEqual(self.client.post(base + "/decisions/" + decision["id"] + "/resolve", json={"resolution": "Attempt to replace the signed decision."}).status_code, 409)

    def test_workspace_blocker_applies_to_future_requirements_and_private_decisions(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}"
        decision = self.client.post(base + "/decisions", json={"question": "Which business unit owns this process?", "owner_role": "Sponsor"}).json()
        row = self.client.post(base + "/items", json=self.payload(source)).json()
        self.assertEqual(self.client.post(base + "/items/" + row["id"] + "/validate", json={"revision": 1, "reviewer_role": "DTL", "validation_note": "Ready for delivery review."}).status_code, 409)
        other = self.workspace()
        self.assertEqual(self.client.post(f"{self.path}/{other}/decisions", json={"requirement_id": row["id"], "question": "Which business unit owns this process?", "owner_role": "Sponsor"}).status_code, 422)
        self.user.id = "other"
        self.assertEqual(self.client.post(base + "/decisions/" + decision["id"] + "/resolve", json={"resolution": "I cannot access this workspace."}).status_code, 404)

    def test_nonblocking_question_preserves_agreement(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}"
        row = self.client.post(base + "/items", json=self.payload(source)).json()
        self.client.post(base + "/decisions", json={"requirement_id": row["id"], "question": "Could a future phase support extra languages?", "owner_role": "Product Owner", "blocking": False})
        self.assertEqual(self.client.get(base).json()["requirements"][0]["revision"], 1)
        response = self.client.post(base + "/items/" + row["id"] + "/validate", json={"revision": 1, "reviewer_role": "DTL", "validation_note": "Current scope is confirmed."})
        self.assertEqual(response.status_code, 200, response.text)

    def test_email_preview_is_private_and_does_not_save_sources(self):
        import base64
        workspace = self.workspace()
        payload = {"content_base64": base64.b64encode(b"Subject: Process review\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nAcknowledge each request within thirty seconds.").decode()}
        response = self.client.post(f"{self.path}/{workspace}/email-preview", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], "Process review")
        self.assertEqual(self.client.get(f"{self.path}/{workspace}").json()["sources"], [])
        self.assertEqual(self.client.post(f"{self.path}/{workspace}/email-preview", json={"content_base64": "invalid!"}).status_code, 422)
        self.user.id = "other"
        self.assertEqual(self.client.post(f"{self.path}/{workspace}/email-preview", json=payload).status_code, 404)

    def test_word_preview_is_private_and_needs_explicit_source_save(self):
        from tests.test_requirement_docx import document
        workspace = self.workspace()
        payload = {"content_base64": document("<w:p><w:r><w:t>Confirm receipt within thirty seconds.</w:t></w:r></w:p>")}
        url = f"{self.path}/{workspace}/docx-preview"
        response = self.client.post(url, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Confirm receipt", response.json()["content"])
        self.assertEqual(self.client.get(f"{self.path}/{workspace}").json()["sources"], [])
        self.assertEqual(self.client.post(url, json={"content_base64": "invalid"}).status_code, 422)
        self.user.id = "other"
        self.assertEqual(self.client.post(url, json=payload).status_code, 404)

    def test_deferred_requirement_preserves_evidence_but_cannot_enter_delivery(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}/items"
        payload = {**self.payload(source), "priority": "wont"}
        row = self.client.post(base, json=payload).json()
        route = base + "/" + row["id"]
        review = {"revision": 1, "reviewer_role": "Product Owner", "validation_note": "Reviewed the deferred business need."}
        self.assertEqual(self.client.post(route + "/validate", json=review).status_code, 409)
        self.assertEqual(self.client.post(route + "/story", json={"revision": 1}).status_code, 409)
        self.user.role = "admin"
        manager = self.ai_manager({})
        with patch.object(main, "llm_mgr", manager):
            response = self.client.post(route + "/assist", json={"revision": 1, "mode": "story"}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 409)
        manager.analyze.assert_not_awaited()
        restored = self.client.put(route, json={**payload, "priority": "should", "revision": 1}).json()
        self.assertEqual(restored["evidence_quote"], payload["evidence_quote"])
        self.assertEqual(self.client.post(route + "/validate", json={**review, "revision": restored["revision"]}).status_code, 200)

    def test_pdf_preview_is_private_and_never_creates_evidence_implicitly(self):
        from tests.test_requirement_pdf import pdf_source
        workspace = self.workspace()
        url = f"{self.path}/{workspace}/pdf-preview"
        response = self.client.post(url, json={"content_base64": pdf_source()})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("[Page 1]", response.json()["content"])
        self.assertEqual(self.client.get(f"{self.path}/{workspace}").json()["sources"], [])
        self.user.id = "other"
        self.assertEqual(self.client.post(url, json={"content_base64": pdf_source()}).status_code, 404)

    def test_history_preserves_previous_signoff_and_story_after_edit_and_blocker(self):
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}"
        row = self.client.post(base + "/items", json=self.payload(source)).json()
        item = base + "/items/" + row["id"]
        signed = self.client.post(item + "/validate", json={"revision": 1, "reviewer_role": "Product Owner", "validation_note": "Original business agreement."}).json()
        story = self.client.post(item + "/story", json={"revision": signed["revision"]}).json()
        self.client.put(item, json={**self.payload(source), "revision": story["revision"], "benefit": "A revised business outcome"})
        self.client.post(base + "/decisions", json={"question": "Who owns the revised business outcome?", "owner_role": "Sponsor"})
        history = self.client.get(item + "/history").json()
        self.assertEqual(history["total"], 5)
        edited = next(entry for entry in history["items"] if entry["action"] == "edited")
        self.assertEqual(edited["before"]["validation_note"], "Original business agreement.")
        self.assertEqual(edited["before"]["story"]["reference"], "US-001")
        self.assertIsNone(edited["after"]["story"])
        self.assertEqual(edited["actor_id"], "owner")
        self.assertEqual(edited["after"]["benefit"], "A revised business outcome")
        self.assertEqual(self.client.get(item + "/history?offset=5").json()["items"], [])
        self.assertEqual(self.client.get(item + "/history?offset=-1").status_code, 422)
        other_workspace = self.workspace()
        self.assertEqual(self.client.get(f"{self.path}/{other_workspace}/items/{row['id']}/history").status_code, 404)
        self.user.id = "other"
        self.assertEqual(self.client.get(item + "/history").status_code, 404)

    def test_failed_history_write_rolls_back_requirement_changes(self):
        from app.backend.database import RequirementHistoryRecord
        workspace = self.workspace()
        source = self.source(workspace)
        row = self.client.post(f"{self.path}/{workspace}/items", json=self.payload(source)).json()
        def fail_history(*args):
            raise RuntimeError("Simulated unavailable history storage")
        event.listen(RequirementHistoryRecord, "before_insert", fail_history)
        try:
            with self.assertRaises(RuntimeError):
                self.client.put(f"{self.path}/{workspace}/items/{row['id']}", json={**self.payload(source), "revision": 1, "title": "Must roll back"})
        finally:
            event.remove(RequirementHistoryRecord, "before_insert", fail_history)
        saved = self.client.get(f"{self.path}/{workspace}").json()["requirements"][0]
        self.assertEqual(saved["title"], row["title"])
        self.assertEqual(saved["revision"], 1)

    def test_exact_source_reimport_reuses_evidence_without_overwriting_metadata(self):
        workspace = self.workspace()
        source = self.source(workspace)
        route = f"{self.path}/{workspace}/sources"
        content = "Every invoice must receive an acknowledgement within 30 seconds."
        response = self.client.post(route, json={"title": "Renamed copy", "kind": "document", "content": "  " + content + "  "})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["reused"])
        self.assertEqual(response.json()["id"], source)
        self.assertEqual(response.json()["title"], "Operations SOP")
        self.assertEqual(response.json()["kind"], "sop")
        self.assertEqual(len(self.client.get(f"{self.path}/{workspace}").json()["sources"]), 1)
        changed = self.client.post(route, json={"title": "Revised SOP", "kind": "sop", "content": content.replace("30", "45")})
        self.assertEqual(changed.status_code, 201)
        self.assertNotEqual(changed.json()["id"], source)
        other = self.workspace()
        copy = self.client.post(f"{self.path}/{other}/sources", json={"title": "Same text, separate initiative", "kind": "sop", "content": content})
        self.assertEqual(copy.status_code, 201)
        self.assertNotEqual(copy.json()["id"], source)

    def test_source_reuse_remains_possible_at_source_limit(self):
        workspace = self.workspace()
        source = self.source(workspace)
        route = f"{self.path}/{workspace}/sources"
        for index in range(49):
            response = self.client.post(route, json={"title": f"Material {index}", "kind": "document", "content": f"Distinct supporting material number {index}."})
            self.assertEqual(response.status_code, 201)
        reused = self.client.post(route, json={"title": "Copy", "kind": "sop", "content": "Every invoice must receive an acknowledgement within 30 seconds."})
        self.assertEqual(reused.status_code, 200)
        self.assertEqual(reused.json()["id"], source)
        self.assertEqual(self.client.post(route, json={"title": "Over limit", "kind": "document", "content": "An additional new source over the limit."}).status_code, 409)

    def test_history_uses_unique_revision_order_without_temporary_sort(self):
        from datetime import datetime, timedelta
        from sqlalchemy.exc import IntegrityError
        from app.backend.database import RequirementHistoryRecord
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}/items"
        row = self.client.post(base, json=self.payload(source)).json()
        route = base + "/" + row["id"]
        for index in range(11):
            row = self.client.put(route, json={**self.payload(source), "revision": row["revision"], "title": f"Change {index}"}).json()
        with self.sessions() as db:
            events = db.query(RequirementHistoryRecord).filter_by(requirement_id=row["id"]).all()
            for entry in events:
                entry.created_at = datetime(2026, 1, 1) - timedelta(seconds=entry.revision)
            db.commit()
        statements = []
        def capture(connection, cursor, statement, parameters, context, executemany):
            if "FROM requirement_history" in statement and "ORDER BY" in statement:
                statements.append((statement, parameters))
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            first = self.client.get(route + "/history").json()
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual([item["revision"] for item in first["items"]], list(range(12, 2, -1)))
        second = self.client.get(route + "/history?offset=10").json()
        self.assertEqual([item["revision"] for item in second["items"]], [2, 1])
        with self.engine.connect() as connection:
            plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statements[0][0], statements[0][1]).all()
        self.assertNotIn("TEMP B-TREE", str(plan))
        with self.sessions() as db:
            db.add(RequirementHistoryRecord(id="duplicate", requirement_id=row["id"], actor_id="owner", action="edited", revision=12, after_json="{}"))
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_ai_can_explore_a_later_passage_without_sending_the_document_prefix(self):
        self.user.role = "admin"
        workspace = self.workspace()
        excerpt = "Escalate unacknowledged supplier requests after five minutes."
        source = self.client.post(f"{self.path}/{workspace}/sources", json={"title": "Long operations guide", "kind": "sop", "content": "Earlier context without the exception policy. " * 1000 + excerpt}).json()["id"]
        candidate = {key: value for key, value in self.payload(source).items() if key != "source_id"}
        candidate.update(evidence_quote=excerpt, assumptions=[])
        manager = self.ai_manager({"candidates": [candidate, {**candidate, "evidence_quote": "Earlier context without the exception policy."}], "questions": []})
        with patch.object(main, "llm_mgr", manager):
            response = self.client.post(f"{self.path}/{workspace}/sources/{source}/gather", json={"excerpt": excerpt}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"], "excerpt")
        self.assertEqual(response.json()["discarded_candidates"], 1)
        self.assertFalse(response.json()["source_truncated"])
        self.assertEqual(response.json()["candidates"][0]["evidence_quote"], excerpt)
        prompt = json.loads(manager.analyze.call_args.args[0])
        self.assertEqual(prompt["content"], excerpt)
        self.assertNotIn("Earlier context", manager.analyze.call_args.args[0])
        self.assertEqual(self.client.get(f"{self.path}/{workspace}").json()["requirements"], [])

    def test_ai_passage_must_match_saved_evidence_before_budget_or_provider_use(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        manager = self.ai_manager({"candidates": [], "questions": []})
        with patch.object(main, "llm_mgr", manager):
            for excerpt in ["This sentence is not in the saved source.", "x" * 12001, "short"]:
                response = self.client.post(f"{self.path}/{workspace}/sources/{source}/gather", json={"excerpt": excerpt}, headers={"Origin": "http://testserver"})
                self.assertEqual(response.status_code, 422)
        manager.analyze.assert_not_awaited()
        with self.sessions() as db:
            self.assertEqual(db.query(AIUsageEventRecord).count(), 0)

    def test_cross_review_is_scoped_versioned_and_never_mutates_requirements(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}"
        first = self.client.post(base + "/items", json=self.payload(source)).json()
        second = self.client.post(base + "/items", json={**self.payload(source), "title": "Exception handling"}).json()
        finding = {"category": "overlap", "references": ["REQ-001", "REQ-002"], "finding": "Both requirements describe acknowledgement behavior.", "question": "Should the normal and exception paths share the same acceptance criteria?"}
        manager = self.ai_manager({"findings": [finding]})
        with patch.object(main, "llm_mgr", manager):
            self.assertEqual(self.client.post(base + "/cross-review", json={"requirement_ids": [first["id"], second["id"]]}).status_code, 403)
            response = self.client.post(base + "/cross-review", json={"requirement_ids": [first["id"], second["id"]]}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["findings"], [finding])
        self.assertEqual([item["revision"] for item in response.json()["requirements"]], [1, 1])
        prompt = json.loads(manager.analyze.call_args.args[0])
        self.assertIn("REQ-001", prompt)
        self.assertIn("REQ-002", prompt)
        detail = self.client.get(base).json()
        self.assertEqual([item["status"] for item in detail["requirements"]], ["draft", "draft"])
        self.assertEqual(detail["decisions"], [])
        with self.sessions() as db:
            self.assertEqual(db.query(AIUsageEventRecord).count(), 1)

    def test_cross_review_rejects_cross_workspace_selection_and_invented_references(self):
        self.user.role = "admin"
        workspace = self.workspace()
        source = self.source(workspace)
        base = f"{self.path}/{workspace}"
        first = self.client.post(base + "/items", json=self.payload(source)).json()
        second = self.client.post(base + "/items", json={**self.payload(source), "title": "Track exceptions"}).json()
        manager = self.ai_manager({"findings": [{"category": "dependency", "references": ["REQ-999"], "finding": "Unknown dependency.", "question": "Who owns this unknown dependency?"}]})
        with patch.object(main, "llm_mgr", manager):
            for ids in [[first["id"]], [first["id"], first["id"]], [first["id"], "unavailable"]]:
                self.assertEqual(self.client.post(base + "/cross-review", json={"requirement_ids": ids}, headers={"Origin": "http://testserver"}).status_code, 422)
            manager.analyze.assert_not_awaited()
            response = self.client.post(base + "/cross-review", json={"requirement_ids": [first["id"], second["id"]]}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 502, response.text)

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

    def test_requirement_serialization_parses_criteria_once_and_preserves_quality_feedback(self):
        from app.backend.requirements_gathering import requirement_out
        values = self.payload("source")
        criteria = values.pop("acceptance_criteria")
        criteria.append(criteria[0].upper())
        row = BusinessRequirementRecord(id="requirement", workspace_id="workspace", number=1,
                                        acceptance_json=json.dumps(criteria), **values)
        original_loads = json.loads
        with patch("app.backend.requirements_gathering.json.loads", wraps=original_loads) as loads:
            result = requirement_out(row)
        loads.assert_called_once_with(row.acceptance_json)
        self.assertEqual(result["acceptance_criteria"], criteria)
        self.assertIn("Remove duplicate acceptance criteria.", result["quality_issues"])
        row.acceptance_json = "[]"
        self.assertIn("Add at least one testable acceptance criterion.", requirement_out(row)["quality_issues"])

    def test_workspace_overview_does_not_load_document_bodies(self):
        workspace = self.workspace()
        source = self.source(workspace)
        from app.backend.database import RequirementSourceRecord, RequirementDecisionRecord
        values = self.payload(source)
        criteria = values.pop("acceptance_criteria")
        with self.sessions() as db:
            db.add_all([RequirementSourceRecord(id=f"material-{i}", workspace_id=workspace, title=f"Material {i}",
                        kind="document", content="x" * 100000, content_sha256="0" * 64) for i in range(49)])
            db.add_all([BusinessRequirementRecord(id=f"requirement-{i}", workspace_id=workspace, number=i + 1,
                        acceptance_json=json.dumps(criteria), **values) for i in range(200)])
            db.add_all([RequirementDecisionRecord(id=f"decision-{i}", workspace_id=workspace,
                        question="Which team owns this outcome?", owner_role="Operations", blocking=False) for i in range(200)])
            db.commit()
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
        self.assertTrue(all("content" not in item for item in response.json()["sources"]))
        self.assertEqual(len(response.json()["sources"]), 50)
        self.assertEqual(len(response.json()["requirements"]), 200)
        self.assertEqual(len(response.json()["decisions"]), 200)
        self.assertEqual(len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]), 4)

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
