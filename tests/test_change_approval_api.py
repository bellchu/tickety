import unittest
import asyncio
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    ChangeApprovalRecord,
    ChangeRecord,
    SessionRecord,
    UserRecord,
    get_db,
)
from app.backend.schema import ChangeApprovalCreate


class ChangeApprovalApiTests(unittest.TestCase):
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
                UserRecord(id="agent", name="Assigned Agent", role="agent", is_active=True),
                UserRecord(id="other-agent", name="Other Agent", role="agent", is_active=True),
                SessionRecord(token="admin-session", user_id="admin"),
                SessionRecord(token="agent-session", user_id="agent"),
                SessionRecord(token="other-session", user_id="other-agent"),
                ChangeRecord(
                    id="change-1",
                    title="Rotate service certificates",
                    status="Submitted",
                    requested_by="other-agent",
                ),
                ChangeApprovalRecord(
                    change_id="change-1",
                    approver_id="agent",
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
        self.session_local_patch = patch.object(main, "SessionLocal", self.session_factory)
        self.session_local_patch.start()
        self.auth_patch = patch.object(main, "_auth_required_for_request", return_value=True)
        self.auth_patch.start()
        self.demo_patch = patch.object(main.settings_module, "is_demo_mode", return_value=False)
        self.demo_patch.start()
        self.client = TestClient(main.app)
        self.headers = {"Sec-Fetch-Site": "same-origin"}

    def tearDown(self):
        self.demo_patch.stop()
        self.auth_patch.stop()
        self.session_local_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _decide(self, token: str, decision: str = "approved"):
        self.client.cookies.set(main.SESSION_COOKIE, token)
        return self.client.patch(
            "/changes/change-1/approvals/agent",
            headers=self.headers,
            json={"decision": decision, "comment": "Reviewed"},
        )

    def test_exact_decision_route_reaches_assigned_agent_through_middleware(self):
        self.assertIsNone(
            main._roles_required_for_request(
                "/changes/change-1/approvals/agent", "PATCH"
            )
        )

        response = self._decide("agent-session")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"], "approved")
        with self.session_factory() as db:
            approval = db.query(ChangeApprovalRecord).one()
            self.assertEqual(approval.decision, "approved")
            self.assertIsNotNone(approval.decided_at)

    def test_unassigned_agent_remains_forbidden_by_handler(self):
        response = self._decide("other-session")

        self.assertEqual(response.status_code, 403, response.text)
        with self.session_factory() as db:
            self.assertIsNone(db.query(ChangeApprovalRecord).one().decision)

    def test_admin_can_decide_an_assigned_approval(self):
        response = self._decide("admin-session")

        self.assertEqual(response.status_code, 200, response.text)

    def test_requester_cannot_use_admin_override_to_decide_their_change(self):
        with self.session_factory() as db:
            change = db.get(ChangeRecord, "change-1")
            change.requested_by = "admin"
            db.commit()

        response = self._decide("admin-session")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json(), {"detail": "Requester cannot approve their own change"})
        with self.session_factory() as db:
            self.assertIsNone(db.query(ChangeApprovalRecord).one().decision)

    def test_decided_approval_cannot_be_overwritten(self):
        first = self._decide("agent-session", "approved")
        second = self._decide("agent-session", "rejected")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json(), {"detail": "Approval already decided"})
        with self.session_factory() as db:
            approval = db.query(ChangeApprovalRecord).one()
            self.assertEqual(approval.decision, "approved")
            self.assertEqual(approval.comment, "Reviewed")

    def test_manual_transition_waits_for_every_approval(self):
        now = datetime.utcnow()
        with self.session_factory() as db:
            change = db.get(ChangeRecord, "change-1")
            change.rollback_plan = "Restore the previous certificate"
            change.test_plan = "Verify TLS health checks"
            change.scheduled_start = now + timedelta(hours=1)
            change.scheduled_end = now + timedelta(hours=2)
            first = db.query(ChangeApprovalRecord).one()
            first.decision = "approved"
            first.decided_at = now
            db.add(ChangeApprovalRecord(
                change_id="change-1",
                approver_id="admin",
            ))
            db.commit()

        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        blocked = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"status": "Completed"},
        )

        self.assertEqual(blocked.status_code, 400, blocked.text)
        self.assertEqual(blocked.json(), {"detail": "All CAB approvals must be decided"})
        with self.session_factory() as db:
            self.assertEqual(db.get(ChangeRecord, "change-1").status, "Submitted")

    def test_approval_cannot_be_added_after_review_closes(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        with self.session_factory() as db:
            change = db.get(ChangeRecord, "change-1")
            change.status = "Approved"
            db.commit()

        response = self.client.post(
            "/changes/change-1/approvals",
            headers=self.headers,
            json={"approver_id": "admin"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json(),
            {"detail": "Approvals can only be added before change execution"},
        )
        with self.session_factory() as db:
            self.assertEqual(db.query(ChangeApprovalRecord).count(), 1)

    def test_approvers_must_be_active_supported_operational_users(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        with self.session_factory() as db:
            db.add_all([
                UserRecord(
                    id="inactive-reviewer",
                    name="Inactive Reviewer",
                    role="agent",
                    is_active=False,
                ),
                UserRecord(
                    id="unsupported-reviewer",
                    name="Unsupported Reviewer",
                    role="auditor",
                    is_active=True,
                ),
            ])
            db.commit()

        responses = (
            self.client.post(
                "/changes/change-1/approvals",
                headers=self.headers,
                json={"approver_id": "missing-reviewer"},
            ),
            self.client.post(
                "/changes/change-1/approvals",
                headers=self.headers,
                json={"approver_id": "inactive-reviewer"},
            ),
            self.client.post(
                "/changes/change-1/approvals",
                headers=self.headers,
                json={"approver_id": "unsupported-reviewer"},
            ),
        )

        self.assertEqual(responses[0].status_code, 404, responses[0].text)
        self.assertEqual(responses[1].status_code, 409, responses[1].text)
        self.assertEqual(responses[2].status_code, 409, responses[2].text)
        with self.session_factory() as db:
            self.assertEqual(db.query(ChangeApprovalRecord).count(), 1)

    def test_user_deactivation_rejects_pending_approvals_until_decided(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        patched = self.client.patch(
            "/users/agent",
            headers=self.headers,
            json={"is_active": False},
        )
        deleted = self.client.delete("/users/agent", headers=self.headers)

        self.assertEqual(patched.status_code, 409, patched.text)
        self.assertEqual(deleted.status_code, 409, deleted.text)
        with self.session_factory() as db:
            self.assertTrue(db.get(UserRecord, "agent").is_active)

        decided = self._decide("agent-session", "approved")
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        deactivated = self.client.delete("/users/agent", headers=self.headers)

        self.assertEqual(decided.status_code, 200, decided.text)
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        with self.session_factory() as db:
            self.assertFalse(db.get(UserRecord, "agent").is_active)

    def test_concurrent_approval_add_and_deactivation_preserve_invariant(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database_file:
            engine = create_engine(
                f"sqlite:///{database_file.name}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            session_factory = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            with session_factory() as db:
                db.add(UserRecord(
                    id="race-admin",
                    name="Race Admin",
                    role="admin",
                    is_active=True,
                ))
                db.commit()

            observed_orders = set()
            for index in range(12):
                change_id = f"race-change-{index}"
                approver_id = f"race-approver-{index}"
                with session_factory() as db:
                    db.add_all([
                        UserRecord(
                            id=approver_id,
                            name=f"Race Approver {index}",
                            role="agent",
                            is_active=True,
                        ),
                        ChangeRecord(
                            id=change_id,
                            title=f"Race Change {index}",
                            status="Submitted",
                            requested_by="race-admin",
                        ),
                    ])
                    db.commit()

                barrier = threading.Barrier(2)
                add_finished = threading.Event()
                deactivation_finished = threading.Event()

                def add_approval():
                    with session_factory() as db:
                        actor = db.get(UserRecord, "race-admin")
                        if index == 1:
                            if not deactivation_finished.wait(10):
                                raise AssertionError("deactivation winner did not finish")
                        elif index != 0:
                            barrier.wait(timeout=10)
                        try:
                            asyncio.run(main.add_change_approval(
                                change_id,
                                ChangeApprovalCreate(approver_id=approver_id),
                                db,
                                actor,
                            ))
                            return 201
                        except HTTPException as exc:
                            return exc.status_code
                        finally:
                            add_finished.set()

                def deactivate():
                    with session_factory() as db:
                        actor = db.get(UserRecord, "race-admin")
                        if index == 0:
                            if not add_finished.wait(10):
                                raise AssertionError("approval winner did not finish")
                        elif index != 1:
                            barrier.wait(timeout=10)
                        try:
                            asyncio.run(main.delete_user(approver_id, db, actor))
                            return 200
                        except HTTPException as exc:
                            return exc.status_code
                        finally:
                            deactivation_finished.set()

                with ThreadPoolExecutor(max_workers=2) as executor:
                    add_future = executor.submit(add_approval)
                    deactivate_future = executor.submit(deactivate)
                    outcome = (add_future.result(15), deactivate_future.result(15))

                self.assertIn(outcome, {(201, 409), (409, 200)})
                observed_orders.add(outcome)
                with session_factory() as db:
                    user = db.get(UserRecord, approver_id)
                    pending = db.query(ChangeApprovalRecord).filter(
                        ChangeApprovalRecord.change_id == change_id,
                        ChangeApprovalRecord.approver_id == approver_id,
                        ChangeApprovalRecord.decided_at.is_(None),
                    ).first()
                    self.assertFalse(pending and not user.is_active)

            self.assertEqual(observed_orders, {(201, 409), (409, 200)})
            engine.dispose()

    def test_blank_execution_plans_do_not_auto_approve(self):
        now = datetime.utcnow()
        with self.session_factory() as db:
            change = db.get(ChangeRecord, "change-1")
            change.rollback_plan = "   "
            change.test_plan = "\t"
            change.scheduled_start = now + timedelta(hours=1)
            change.scheduled_end = now + timedelta(hours=2)
            db.commit()

        response = self._decide("agent-session")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["change_status"], "CAB Review")
        with self.session_factory() as db:
            self.assertEqual(db.get(ChangeRecord, "change-1").status, "CAB Review")

    def test_change_and_approval_payloads_are_bounded(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")

        blank_title = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"title": "   "},
        )
        long_comment = self.client.patch(
            "/changes/change-1/approvals/agent",
            headers=self.headers,
            json={"decision": "approved", "comment": "x" * 5_001},
        )

        self.assertEqual(blank_title.status_code, 422, blank_title.text)
        self.assertEqual(long_comment.status_code, 422, long_comment.text)
        with self.session_factory() as db:
            self.assertEqual(db.get(ChangeRecord, "change-1").title, "Rotate service certificates")
            self.assertIsNone(db.query(ChangeApprovalRecord).one().decision)

    def test_change_schedule_normalizes_offsets_before_window_validation(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")

        response = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={
                "scheduled_start": "2026-08-26T10:00:00Z",
                "scheduled_end": "2026-08-26T11:00:00",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scheduled_start"], "2026-08-26T10:00:00")
        self.assertEqual(response.json()["scheduled_end"], "2026-08-26T11:00:00")

    def test_change_assignment_requires_an_existing_active_user(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        with self.session_factory() as db:
            db.add(UserRecord(
                id="inactive-agent",
                name="Inactive Agent",
                role="agent",
                is_active=False,
            ))
            db.commit()

        missing_create = self.client.post(
            "/changes",
            headers=self.headers,
            json={"title": "Missing owner", "assigned_to": "missing-agent"},
        )
        inactive_create = self.client.post(
            "/changes",
            headers=self.headers,
            json={"title": "Inactive owner", "assigned_to": "inactive-agent"},
        )
        missing_update = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"assigned_to": "missing-agent"},
        )

        self.assertEqual(missing_create.status_code, 404, missing_create.text)
        self.assertEqual(inactive_create.status_code, 409, inactive_create.text)
        self.assertEqual(missing_update.status_code, 404, missing_update.text)
        with self.session_factory() as db:
            self.assertEqual(db.get(ChangeRecord, "change-1").assigned_to, None)

    def test_change_assignment_can_be_cleared_explicitly(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        with self.session_factory() as db:
            db.get(ChangeRecord, "change-1").assigned_to = "agent"
            db.commit()

        response = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"assigned_to": None},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["assigned_to"])

    def test_change_optional_fields_can_be_cleared_explicitly(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        now = datetime.utcnow()
        with self.session_factory() as db:
            change = db.get(ChangeRecord, "change-1")
            change.description = "Implementation detail"
            change.impact = "Customer-facing interruption"
            change.rollback_plan = "Restore previous version"
            change.test_plan = "Run smoke tests"
            change.scheduled_start = now + timedelta(hours=1)
            change.scheduled_end = now + timedelta(hours=2)
            db.commit()

        response = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={
                "description": None,
                "impact": None,
                "rollback_plan": None,
                "test_plan": None,
                "scheduled_start": None,
                "scheduled_end": None,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["description"], "")
        for field in (
            "impact", "rollback_plan", "test_plan",
            "scheduled_start", "scheduled_end",
        ):
            self.assertIsNone(body[field])

    def test_change_lifecycle_is_forward_only_and_completion_is_immutable(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        now = datetime.utcnow()
        with self.session_factory() as db:
            change = db.get(ChangeRecord, "change-1")
            change.rollback_plan = "Restore the prior release"
            change.test_plan = "Run the production smoke suite"
            change.scheduled_start = now + timedelta(hours=1)
            change.scheduled_end = now + timedelta(hours=2)
            db.commit()

        review = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"status": "CAB Review"},
        )
        approved = self._decide("agent-session", "approved")
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        in_progress = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"status": "In Progress"},
        )
        completed = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"status": "Completed"},
        )
        reopen = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"status": "Draft"},
        )
        edit_terminal = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"title": "Rewrite completed history"},
        )

        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()["status"], "CAB Review")
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["change_status"], "Approved")
        self.assertEqual(in_progress.status_code, 200, in_progress.text)
        self.assertEqual(in_progress.json()["status"], "In Progress")
        self.assertIsNone(in_progress.json()["completed_at"])
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "Completed")
        self.assertIsNotNone(completed.json()["completed_at"])
        self.assertEqual(reopen.status_code, 409, reopen.text)
        self.assertEqual(edit_terminal.status_code, 409, edit_terminal.text)
        with self.session_factory() as db:
            change = db.get(ChangeRecord, "change-1")
            self.assertEqual(change.status, "Completed")
            self.assertIsNotNone(change.completed_at)
            self.assertEqual(change.title, "Rotate service certificates")

    def test_invalid_change_jumps_and_noncanonical_payloads_are_rejected(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")

        jump = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"status": "Cancelled", "priority": "P1"},
        )
        self.assertEqual(jump.status_code, 200, jump.text)
        self.assertEqual(jump.json()["status"], "Cancelled")
        self.assertEqual(jump.json()["priority"], "P1")

        for payload in (
            {"title": "Starts completed", "status": "Completed"},
            {"title": "Starts approved", "status": "Approved"},
            {"title": "Bad priority", "priority": "Urgent"},
            {"title": "Unknown field", "mystery": "value"},
        ):
            response = self.client.post(
                "/changes",
                headers=self.headers,
                json=payload,
            )
            self.assertEqual(response.status_code, 422, response.text)

        created = self.client.post(
            "/changes",
            headers=self.headers,
            json={"title": "Validate transition graph"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        invalid_jump = self.client.patch(
            f"/changes/{created.json()['id']}",
            headers=self.headers,
            json={"status": "CAB Review"},
        )
        null_status = self.client.patch(
            f"/changes/{created.json()['id']}",
            headers=self.headers,
            json={"status": None},
        )
        self.assertEqual(invalid_jump.status_code, 409, invalid_jump.text)
        self.assertEqual(null_status.status_code, 422, null_status.text)

    def test_only_untouched_draft_changes_can_be_deleted(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        untouched = self.client.post(
            "/changes",
            headers=self.headers,
            json={"title": "Disposable draft"},
        )
        with_history = self.client.post(
            "/changes",
            headers=self.headers,
            json={"title": "Audited draft"},
        )
        self.assertEqual(untouched.status_code, 201, untouched.text)
        self.assertEqual(with_history.status_code, 201, with_history.text)

        approval = self.client.post(
            f"/changes/{with_history.json()['id']}/approvals",
            headers=self.headers,
            json={"approver_id": "agent"},
        )
        deleted = self.client.delete(
            f"/changes/{untouched.json()['id']}",
            headers=self.headers,
        )
        history_blocked = self.client.delete(
            f"/changes/{with_history.json()['id']}",
            headers=self.headers,
        )
        submitted_blocked = self.client.delete(
            "/changes/change-1",
            headers=self.headers,
        )

        self.assertEqual(approval.status_code, 201, approval.text)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(history_blocked.status_code, 409, history_blocked.text)
        self.assertEqual(submitted_blocked.status_code, 409, submitted_blocked.text)
        with self.session_factory() as db:
            self.assertIsNone(db.get(ChangeRecord, untouched.json()["id"]))
            self.assertIsNotNone(db.get(ChangeRecord, with_history.json()["id"]))

    def test_terminal_change_rejects_new_or_late_approval_decisions(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        cancelled = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"status": "Cancelled"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        add = self.client.post(
            "/changes/change-1/approvals",
            headers=self.headers,
            json={"approver_id": "admin"},
        )
        decide = self._decide("agent-session", "approved")

        self.assertEqual(add.status_code, 409, add.text)
        self.assertEqual(decide.status_code, 409, decide.text)
        with self.session_factory() as db:
            approval = db.query(ChangeApprovalRecord).one()
            self.assertIsNone(approval.decision)
            self.assertEqual(db.get(ChangeRecord, "change-1").status, "Cancelled")

    def test_nul_change_and_approval_inputs_are_rejected(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")

        change = self.client.patch(
            "/changes/change-1",
            headers=self.headers,
            json={"description": "invalid\u0000description"},
        )
        approval = self.client.patch(
            "/changes/change-1/approvals/agent",
            headers=self.headers,
            json={"decision": "approved", "comment": "invalid\u0000comment"},
        )
        search = self.client.get(
            "/changes",
            params={"search": "invalid\u0000search"},
        )

        self.assertEqual(change.status_code, 422, change.text)
        self.assertEqual(approval.status_code, 422, approval.text)
        self.assertEqual(search.status_code, 422, search.text)
        with self.session_factory() as db:
            self.assertIsNone(db.query(ChangeApprovalRecord).one().decision)

    def test_change_register_is_searchable_paginated_and_reports_global_summary(self):
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        with self.session_factory() as db:
            existing = db.get(ChangeRecord, "change-1")
            existing.assigned_to = "agent"
            for index in range(26):
                db.add(ChangeRecord(
                    id=f"change-page-{index:02d}",
                    title=f"Routine rollout {index:02d}",
                    status="In Progress" if index == 0 else "Draft",
                    risk_level="High" if index == 0 else "Low",
                    requested_by="other-agent",
                ))
            db.commit()

        page = self.client.get("/changes", params={"limit": 25, "offset": 0})
        owner_match = self.client.get(
            "/changes",
            params={"search": "Assigned Agent", "limit": 10},
        )

        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(len(page.json()), 25)
        self.assertEqual(page.headers["x-has-more"], "true")
        self.assertEqual(page.headers["x-change-awaiting-review"], "1")
        self.assertEqual(page.headers["x-change-in-progress"], "1")
        self.assertEqual(page.headers["x-change-high-risk"], "1")
        self.assertEqual(owner_match.status_code, 200, owner_match.text)
        self.assertEqual(len(owner_match.json()), 1)
        self.assertEqual(owner_match.json()[0]["assigned_name"], "Assigned Agent")

        invalid_page = self.client.get("/changes", params={"limit": 101})
        self.assertEqual(invalid_page.status_code, 422, invalid_page.text)

    def test_approval_history_is_bounded_stable_and_batch_enriched(self):
        with self.session_factory() as db:
            for index in range(205):
                approver_id = f"reviewer-{index:03d}"
                db.add(UserRecord(
                    id=approver_id,
                    name=f"Reviewer {index:03d}",
                    role="agent",
                    is_active=True,
                ))
                db.add(ChangeApprovalRecord(
                    change_id="change-1",
                    approver_id=approver_id,
                ))
            db.add(ChangeApprovalRecord(
                change_id="change-1",
                approver_id=None,
                decision="approved",
                comment="Retained after account deletion",
                decided_at=datetime.utcnow(),
            ))
            db.commit()

        user_selects = []

        def capture_user_select(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from users" in normalized:
                user_selects.append(normalized)

        with patch.object(main, "_auth_required_for_request", return_value=False):
            event.listen(self.engine, "before_cursor_execute", capture_user_select)
            try:
                pages = [self.client.get("/changes/change-1/approvals")]
                pages.extend(
                    self.client.get(
                        "/changes/change-1/approvals",
                        params={"limit": 50, "offset": offset},
                    )
                    for offset in (50, 100, 150, 200)
                )
            finally:
                event.remove(self.engine, "before_cursor_execute", capture_user_select)

            maximum_page = self.client.get(
                "/changes/change-1/approvals",
                params={"limit": 200},
            )
            oversized_page = self.client.get(
                "/changes/change-1/approvals",
                params={"limit": 201},
            )
            negative_offset = self.client.get(
                "/changes/change-1/approvals",
                params={"offset": -1},
            )
            missing_change = self.client.get("/changes/missing/approvals")

        self.assertEqual([response.status_code for response in pages], [200] * 5)
        self.assertEqual([len(response.json()) for response in pages], [50, 50, 50, 50, 7])
        self.assertEqual([response.headers["x-page-offset"] for response in pages], ["0", "50", "100", "150", "200"])
        self.assertEqual([response.headers["x-page-limit"] for response in pages], ["50"] * 5)
        self.assertEqual([response.headers["x-has-more"] for response in pages], ["true", "true", "true", "true", "false"])

        approvals = [approval for response in pages for approval in response.json()]
        self.assertEqual(len({approval["id"] for approval in approvals}), 207)
        self.assertEqual([approval["id"] for approval in approvals], sorted(approval["id"] for approval in approvals))
        named_approvals = [approval for approval in approvals if approval["approver_id"]]
        anonymous_approvals = [approval for approval in approvals if not approval["approver_id"]]
        self.assertTrue(all(approval["approver_name"] for approval in named_approvals))
        self.assertEqual(len(anonymous_approvals), 1)
        self.assertIsNone(anonymous_approvals[0]["approver_name"])
        self.assertEqual(anonymous_approvals[0]["decision"], "approved")
        self.assertEqual(len(user_selects), 5, user_selects)

        self.assertEqual(maximum_page.status_code, 200, maximum_page.text)
        self.assertEqual(len(maximum_page.json()), 200)
        self.assertEqual(maximum_page.headers["x-page-limit"], "200")
        self.assertEqual(maximum_page.headers["x-has-more"], "true")
        self.assertEqual(oversized_page.status_code, 422, oversized_page.text)
        self.assertEqual(negative_offset.status_code, 422, negative_offset.text)
        self.assertEqual(missing_change.status_code, 404, missing_change.text)

    def test_route_exception_is_exact_and_still_requires_authentication(self):
        self.assertEqual(
            main._roles_required_for_request(
                "/changes/change-1/approvals/agent/extra", "PATCH"
            ),
            {"admin", "supervisor"},
        )

        response = self.client.patch(
            "/changes/change-1/approvals/agent",
            headers=self.headers,
            json={"decision": "approved"},
        )

        self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()
