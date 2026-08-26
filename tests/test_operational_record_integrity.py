import unittest
import re
import uuid
import asyncio
import tempfile
import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    AssetRecord,
    Base,
    ChangeRecord,
    ChangeTicketLinkRecord,
    KbArticleRecord,
    ProblemRecord,
    ProblemTicketLinkRecord,
    ProjectRecord,
    RecognitionRecord,
    ServiceItemRecord,
    ServiceRequestRecord,
    SessionRecord,
    TicketCommentRecord,
    TicketRecord,
    TimeEntryRecord,
    UserRecord,
    get_db,
)
from app.backend.schema import (
    BulkAction,
    TicketCommentCreate,
    TicketUpdate,
    TimeEntryCreate,
)


class OperationalRecordIntegrityTests(unittest.TestCase):
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
                UserRecord(id="owner", name="Owner", role="agent", is_active=True),
                UserRecord(
                    id="auditor",
                    name="Unsupported Auditor",
                    role="auditor",
                    is_active=True,
                ),
                UserRecord(
                    id="inactive-owner",
                    name="Inactive Owner",
                    role="agent",
                    is_active=False,
                ),
                SessionRecord(token="admin-session", user_id="admin"),
                ProjectRecord(
                    id="project-1",
                    name="Project One",
                    key="ONE",
                    lead_id="owner",
                ),
                ProblemRecord(
                    id="problem-1",
                    title="Intermittent failure",
                    status="Closed",
                    priority="P2",
                    assigned_to="owner",
                    root_cause="Legacy root cause",
                    resolution="Legacy resolution",
                    closed_at=datetime(2026, 8, 26, 12, 0),
                ),
                AssetRecord(
                    id="asset-1",
                    name="Edge Router",
                    asset_type="Network",
                    asset_tag="EDGE-1",
                    status="In Use",
                    owner_id="owner",
                    location="Rack A",
                ),
                AssetRecord(
                    id="asset-retired",
                    name="Retired router",
                    asset_type="Network",
                    status="Retired",
                    owner_id="owner",
                ),
                AssetRecord(
                    id="asset-broken",
                    name="Broken router",
                    asset_type="Network",
                    status="Broken",
                    owner_id="owner",
                ),
                ServiceItemRecord(
                    id="service-active",
                    name="Active service",
                    is_active=True,
                ),
                ServiceItemRecord(
                    id="service-inactive",
                    name="Inactive service",
                    is_active=False,
                ),
                TicketRecord(
                    id="ticket-asset",
                    subject="Router incident",
                    asset_id="asset-1",
                ),
                TicketRecord(
                    id="ticket-historical-refs",
                    subject="Historical references",
                    service_id="service-inactive",
                    asset_id="asset-retired",
                ),
                TicketRecord(id="ticket-ref-update", subject="Reference update"),
                TicketRecord(
                    id="ticket-inactive-assignee",
                    subject="Historical inactive assignee",
                    assignee_id="inactive-owner",
                ),
                TicketRecord(
                    id="ticket-request-type",
                    subject="Service request evidence",
                    ticket_type="request",
                ),
                TicketRecord(
                    id="ticket-incident-link",
                    subject="Incident evidence",
                    ticket_type="incident",
                ),
                TicketRecord(id="ticket-delete-problem", subject="Problem history"),
                TicketRecord(id="ticket-delete-change", subject="Change history"),
                TicketRecord(id="ticket-delete-service", subject="Request history"),
                TicketRecord(id="ticket-delete-free", subject="Disposable ticket"),
                TicketRecord(
                    id="ticket-resolution-history",
                    subject="Resolved history",
                    status="New",
                    workflow_status="New",
                    resolved_at=datetime(2026, 8, 25, 12, 0),
                    resolved_by="owner",
                    points_awarded=40,
                    points_awarded_sent=True,
                ),
                TicketRecord(
                    id="ticket-terminal-workflow",
                    subject="Terminal workflow",
                    status="New",
                    workflow_status="Resolved",
                ),
                ChangeRecord(
                    id="change-delete-history",
                    title="Retained change",
                    requested_by="admin",
                ),
                ProblemTicketLinkRecord(
                    problem_id="problem-1",
                    ticket_id="ticket-delete-problem",
                ),
                ChangeTicketLinkRecord(
                    change_id="change-delete-history",
                    ticket_id="ticket-delete-change",
                ),
                ServiceRequestRecord(
                    id="request-delete-history",
                    ticket_id="ticket-delete-service",
                    service_item_id="service-active",
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
        self.session_patch = patch.object(main, "SessionLocal", self.session_factory)
        self.session_patch.start()
        self.client = TestClient(main.app)
        self.client.cookies.set(main.SESSION_COOKIE, "admin-session")
        self.headers = {"Sec-Fetch-Site": "same-origin"}

    def tearDown(self):
        self.session_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    @contextmanager
    def _demo_ticket_writes(self):
        with (
            patch.object(main.settings_module, "is_production_mode", return_value=False),
            patch.object(main, "_automation_enabled", return_value=False),
            patch.object(main, "_reserve_index_write_request"),
            patch.object(main, "_reserve_ai_request"),
            patch.object(main, "_reserve_embedding_request"),
            patch.object(
                main.ticket_vectors,
                "refresh_ticket_documents",
                new=AsyncMock(return_value=None),
            ),
            patch.object(main, "_auto_process", new=AsyncMock(return_value=None)),
            patch.object(
                main.ticket_vectors,
                "upsert_kb_document",
                new=AsyncMock(return_value=None),
            ),
        ):
            yield

    def test_project_references_are_validated_and_optional_fields_can_be_cleared(self):
        missing = self.client.post(
            "/projects",
            headers=self.headers,
            json={"name": "Missing lead", "key": "MISS", "lead_id": "missing"},
        )
        inactive = self.client.post(
            "/projects",
            headers=self.headers,
            json={"name": "Inactive lead", "key": "INACT", "lead_id": "inactive-owner"},
        )
        duplicate = self.client.post(
            "/projects",
            headers=self.headers,
            json={"name": "Duplicate", "key": "one"},
        )
        cleared = self.client.patch(
            "/projects/project-1",
            headers=self.headers,
            json={"lead_id": None, "description": None},
        )

        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(inactive.status_code, 409, inactive.text)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["lead_id"])
        self.assertEqual(cleared.json()["description"], "")

    def test_problem_lifecycle_is_canonical_and_reopening_clears_closed_at(self):
        invalid_status = self.client.patch(
            "/problems/problem-1",
            headers=self.headers,
            json={"status": "closed"},
        )
        reopened = self.client.patch(
            "/problems/problem-1",
            headers=self.headers,
            json={"status": "New", "assigned_to": None},
        )
        incomplete_close = self.client.patch(
            "/problems/problem-1",
            headers=self.headers,
            json={"status": "Closed", "root_cause": None, "resolution": None},
        )
        closed = self.client.patch(
            "/problems/problem-1",
            headers=self.headers,
            json={
                "status": "Closed",
                "root_cause": "Verified root cause",
                "resolution": "Permanent correction",
            },
        )

        self.assertEqual(invalid_status.status_code, 422, invalid_status.text)
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertIsNone(reopened.json()["assigned_to"])
        self.assertIsNone(reopened.json()["closed_at"])
        self.assertEqual(incomplete_close.status_code, 400, incomplete_close.text)
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertIsNotNone(closed.json()["closed_at"])

    def test_problem_and_asset_user_references_fail_cleanly(self):
        for path, payload in (
            ("/problems/problem-1", {"assigned_to": "missing"}),
            ("/assets/asset-1", {"owner_id": "missing"}),
        ):
            with self.subTest(path=path, kind="missing"):
                response = self.client.patch(path, headers=self.headers, json=payload)
                self.assertEqual(response.status_code, 404, response.text)
        for path, payload in (
            ("/problems/problem-1", {"assigned_to": "inactive-owner"}),
            ("/assets/asset-1", {"owner_id": "inactive-owner"}),
        ):
            with self.subTest(path=path, kind="inactive"):
                response = self.client.patch(path, headers=self.headers, json=payload)
                self.assertEqual(response.status_code, 409, response.text)

    def test_asset_fields_clear_duplicate_tags_conflict_and_delete_retires(self):
        duplicate = self.client.post(
            "/assets",
            headers=self.headers,
            json={
                "name": "Duplicate router",
                "asset_type": "Network",
                "asset_tag": "EDGE-1",
            },
        )
        cleared = self.client.patch(
            "/assets/asset-1",
            headers=self.headers,
            json={"asset_tag": None, "owner_id": None, "location": None},
        )
        retired = self.client.delete("/assets/asset-1", headers=self.headers)

        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["asset_tag"])
        self.assertIsNone(cleared.json()["owner_id"])
        self.assertIsNone(cleared.json()["location"])
        self.assertEqual(retired.status_code, 200, retired.text)
        self.assertEqual(retired.json(), {"status": "retired"})
        with self.session_factory() as db:
            self.assertEqual(db.get(AssetRecord, "asset-1").status, "Retired")
            self.assertEqual(db.get(TicketRecord, "ticket-asset").asset_id, "asset-1")

    def test_generated_operational_ids_use_full_uuid_entropy(self):
        with self._demo_ticket_writes():
            project = self.client.post(
                "/projects",
                headers=self.headers,
                json={"name": "Entropy project", "key": "ENTROPY"},
            )
            service = self.client.post(
                "/services",
                headers=self.headers,
                json={"name": "Entropy service"},
            )
            problem = self.client.post(
                "/problems",
                headers=self.headers,
                json={"title": "Entropy problem"},
            )
            asset = self.client.post(
                "/assets",
                headers=self.headers,
                json={"name": "Entropy asset", "asset_type": "Hardware"},
            )
            change = self.client.post(
                "/changes",
                headers=self.headers,
                json={"title": "Entropy change"},
            )
            user = self.client.post(
                "/users",
                headers=self.headers,
                json={
                    "name": "Entropy User",
                    "email": "entropy@example.com",
                    "role": "agent",
                },
            )
            article = self.client.post(
                "/kb",
                headers=self.headers,
                json={"title": "Entropy article", "content": "Draft guidance"},
            )
            self.assertEqual(service.status_code, 201, service.text)
            service_request = self.client.post(
                "/service-requests",
                headers=self.headers,
                json={
                    "ticket_id": "ticket-ref-update",
                    "service_item_id": service.json()["id"],
                },
            )

        responses = {
            "proj": project,
            "svc": service,
            "prob": problem,
            "ast": asset,
            "chg": change,
            "u": user,
            "kb": article,
            "sr": service_request,
        }
        for prefix, response in responses.items():
            with self.subTest(prefix=prefix):
                self.assertIn(response.status_code, (200, 201), response.text)
                self.assertRegex(
                    response.json()["id"],
                    rf"^{prefix}-[0-9a-f]{{32}}$",
                )

    def test_generated_id_collisions_fail_with_409_instead_of_500(self):
        fixed_uuid = uuid.UUID(hex="a" * 32)
        with self.session_factory() as db:
            db.add_all([
                ServiceItemRecord(
                    id=f"svc-{fixed_uuid.hex}",
                    name="Existing fixed service",
                ),
                UserRecord(
                    id=f"u-{fixed_uuid.hex}",
                    name="Existing fixed user",
                    role="agent",
                ),
                KbArticleRecord(
                    id=f"kb-{fixed_uuid.hex}",
                    title="Existing fixed article",
                    slug="existing-fixed-article",
                    status="draft",
                ),
            ])
            db.commit()

        with (
            patch("uuid.uuid4", return_value=fixed_uuid),
            self._demo_ticket_writes(),
        ):
            responses = (
                self.client.post(
                    "/services",
                    headers=self.headers,
                    json={"name": "Colliding service"},
                ),
                self.client.post(
                    "/users",
                    headers=self.headers,
                    json={
                        "name": "Colliding user",
                        "email": "collision@example.com",
                        "role": "agent",
                    },
                ),
                self.client.post(
                    "/kb",
                    headers=self.headers,
                    json={"title": "Colliding article"},
                ),
            )
        for response in responses:
            self.assertEqual(response.status_code, 409, response.text)

    def test_ticket_service_and_asset_references_are_locked_and_validated(self):
        with self._demo_ticket_writes():
            created = self.client.post(
                "/tickets",
                headers=self.headers,
                json={
                    "subject": "Broken router incident",
                    "service_id": "service-active",
                    "asset_id": "asset-broken",
                },
            )
            missing_service = self.client.post(
                "/tickets",
                headers=self.headers,
                json={"subject": "Missing service", "service_id": "missing"},
            )
            inactive_service = self.client.post(
                "/tickets",
                headers=self.headers,
                json={
                    "subject": "Inactive service",
                    "service_id": "service-inactive",
                },
            )
            missing_asset = self.client.post(
                "/tickets",
                headers=self.headers,
                json={"subject": "Missing asset", "asset_id": "missing"},
            )
            retired_asset = self.client.post(
                "/tickets",
                headers=self.headers,
                json={"subject": "Retired asset", "asset_id": "asset-retired"},
            )
            nul_reference = self.client.post(
                "/tickets",
                headers=self.headers,
                json={"subject": "NUL asset", "asset_id": "bad\x00asset"},
            )
            updated = self.client.patch(
                "/tickets/ticket-ref-update",
                headers=self.headers,
                json={
                    "service_id": "service-active",
                    "asset_id": "asset-broken",
                },
            )
            update_inactive = self.client.patch(
                "/tickets/ticket-ref-update",
                headers=self.headers,
                json={"service_id": "service-inactive"},
            )
            update_retired = self.client.patch(
                "/tickets/ticket-ref-update",
                headers=self.headers,
                json={"asset_id": "asset-retired"},
            )
            unchanged_history = self.client.patch(
                "/tickets/ticket-historical-refs",
                headers=self.headers,
                json={
                    "service_id": "service-inactive",
                    "asset_id": "asset-retired",
                },
            )
            cleared_history = self.client.patch(
                "/tickets/ticket-historical-refs",
                headers=self.headers,
                json={"service_id": None, "asset_id": None},
            )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["service_id"], "service-active")
        self.assertEqual(created.json()["asset_id"], "asset-broken")
        self.assertEqual(missing_service.status_code, 404, missing_service.text)
        self.assertEqual(inactive_service.status_code, 409, inactive_service.text)
        self.assertEqual(missing_asset.status_code, 404, missing_asset.text)
        self.assertEqual(retired_asset.status_code, 409, retired_asset.text)
        self.assertEqual(nul_reference.status_code, 422, nul_reference.text)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(update_inactive.status_code, 409, update_inactive.text)
        self.assertEqual(update_retired.status_code, 409, update_retired.text)
        self.assertEqual(unchanged_history.status_code, 200, unchanged_history.text)
        self.assertEqual(cleared_history.status_code, 200, cleared_history.text)
        self.assertIsNone(cleared_history.json()["service_id"])
        self.assertIsNone(cleared_history.json()["asset_id"])

    def test_ticket_assignees_must_remain_active_supported_users(self):
        with self._demo_ticket_writes():
            missing = self.client.patch(
                "/tickets/ticket-ref-update",
                headers=self.headers,
                json={"assignee_id": "missing"},
            )
            inactive = self.client.patch(
                "/tickets/ticket-ref-update",
                headers=self.headers,
                json={"assignee_id": "inactive-owner"},
            )
            unsupported = self.client.patch(
                "/tickets/ticket-ref-update",
                headers=self.headers,
                json={"assignee_id": "auditor"},
            )
            assigned = self.client.patch(
                "/tickets/ticket-ref-update",
                headers=self.headers,
                json={"assignee_id": "owner"},
            )
            unchanged_history = self.client.patch(
                "/tickets/ticket-inactive-assignee",
                headers=self.headers,
                json={"assignee_id": "inactive-owner"},
            )
            bulk_inactive = self.client.post(
                "/tickets/bulk",
                headers=self.headers,
                json={
                    "ticket_ids": ["ticket-asset"],
                    "action": "assign",
                    "value": "inactive-owner",
                },
            )
            bulk_unsupported = self.client.post(
                "/tickets/bulk",
                headers=self.headers,
                json={
                    "ticket_ids": ["ticket-asset"],
                    "action": "assign",
                    "value": "auditor",
                },
            )
            bulk_assigned = self.client.post(
                "/tickets/bulk",
                headers=self.headers,
                json={
                    "ticket_ids": ["ticket-asset"],
                    "action": "assign",
                    "value": "owner",
                },
            )

        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(inactive.status_code, 409, inactive.text)
        self.assertEqual(unsupported.status_code, 409, unsupported.text)
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["assignee_id"], "owner")
        self.assertEqual(unchanged_history.status_code, 200, unchanged_history.text)
        self.assertEqual(
            unchanged_history.json()["assignee_id"],
            "inactive-owner",
        )
        self.assertEqual(bulk_inactive.status_code, 422, bulk_inactive.text)
        self.assertEqual(bulk_unsupported.status_code, 422, bulk_unsupported.text)
        self.assertEqual(bulk_assigned.status_code, 200, bulk_assigned.text)
        with self.session_factory() as db:
            self.assertEqual(db.get(TicketRecord, "ticket-asset").assignee_id, "owner")

    def test_assignment_revalidates_target_after_durable_quota_commit(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database_file:
            engine = create_engine(
                f"sqlite:///{database_file.name}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            session_factory = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            with session_factory() as db:
                db.add_all([
                    UserRecord(
                        id="race-admin",
                        name="Race Admin",
                        role="admin",
                        is_active=True,
                    ),
                    UserRecord(
                        id="generic-target",
                        name="Generic Target",
                        role="agent",
                        is_active=True,
                    ),
                    UserRecord(
                        id="bulk-target",
                        name="Bulk Target",
                        role="agent",
                        is_active=True,
                    ),
                    TicketRecord(id="generic-race", subject="Generic assignment race"),
                    TicketRecord(id="bulk-race", subject="Bulk assignment race"),
                ])
                db.commit()

            def run_race(target_id, operation):
                quota_committed = threading.Event()
                target_deactivated = threading.Event()
                outcome = []

                def reserve_after_preflight(db, _actor_id):
                    db.commit()
                    quota_committed.set()
                    if not target_deactivated.wait(10):
                        raise AssertionError("deactivation did not complete")

                def invoke():
                    with session_factory() as db:
                        actor = db.get(UserRecord, "race-admin")
                        try:
                            outcome.append(asyncio.run(operation(db, actor)))
                        except HTTPException as exc:
                            outcome.append(exc.status_code)

                with (
                    patch.object(
                        main.settings_module,
                        "is_production_mode",
                        return_value=False,
                    ),
                    patch.object(
                        main,
                        "_reserve_index_write_request",
                        side_effect=reserve_after_preflight,
                    ),
                    patch.object(main, "_reserve_embedding_request"),
                    patch.object(main, "_automation_enabled", return_value=False),
                    patch.object(
                        main.ticket_vectors,
                        "refresh_ticket_documents",
                        new=AsyncMock(return_value=None),
                    ),
                ):
                    worker = threading.Thread(target=invoke)
                    worker.start()
                    self.assertTrue(quota_committed.wait(10))
                    with session_factory() as db:
                        target = main._lock_user_record(db, target_id)
                        target.is_active = False
                        db.commit()
                    target_deactivated.set()
                    worker.join(10)
                    self.assertFalse(worker.is_alive())
                self.assertEqual(outcome, [409])

            async def generic_operation(db, actor):
                return await main.update_ticket(
                    "generic-race",
                    TicketUpdate(assignee_id="generic-target"),
                    db,
                    actor,
                )

            async def bulk_operation(db, actor):
                return await main.bulk_action(
                    BulkAction(
                        ticket_ids=["bulk-race"],
                        action="assign",
                        value="bulk-target",
                    ),
                    db,
                    actor,
                )

            run_race("generic-target", generic_operation)
            run_race("bulk-target", bulk_operation)
            with session_factory() as db:
                self.assertIsNone(db.get(TicketRecord, "generic-race").assignee_id)
                self.assertIsNone(db.get(TicketRecord, "bulk-race").assignee_id)
            engine.dispose()

    def test_evidence_writes_reauthorize_after_reassignment(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database_file:
            engine = create_engine(
                f"sqlite:///{database_file.name}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            session_factory = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            with session_factory() as db:
                db.add_all([
                    UserRecord(
                        id="agent-a",
                        name="Agent A",
                        role="agent",
                        is_active=True,
                    ),
                    UserRecord(
                        id="agent-b",
                        name="Agent B",
                        role="agent",
                        is_active=True,
                    ),
                    TicketRecord(
                        id="comment-race",
                        subject="Comment reassignment race",
                        assignee_id="agent-a",
                    ),
                    TicketRecord(
                        id="time-race",
                        subject="Time reassignment race",
                        assignee_id="agent-a",
                    ),
                ])
                db.commit()

            reservation_finished = threading.Event()
            reassigned = threading.Event()
            comment_outcome = []

            def hold_after_reservations(db, _user, _task, **_kwargs):
                db.commit()
                reservation_finished.set()
                if not reassigned.wait(10):
                    raise AssertionError("comment reassignment did not complete")

            def write_comment():
                with session_factory() as db:
                    actor = db.get(UserRecord, "agent-a")
                    try:
                        asyncio.run(main.add_comment(
                            "comment-race",
                            TicketCommentCreate(body="Race evidence"),
                            db,
                            actor,
                        ))
                        comment_outcome.append(201)
                    except HTTPException as exc:
                        comment_outcome.append(exc.status_code)

            with (
                patch.object(
                    main,
                    "_reserve_index_write_request",
                    side_effect=lambda db, _actor_id: db.commit(),
                ),
                patch.object(
                    main,
                    "_reserve_embedding_request",
                    side_effect=hold_after_reservations,
                ),
                patch.object(
                    main.ticket_vectors,
                    "upsert_comment_document",
                    new=AsyncMock(return_value=None),
                ),
            ):
                comment_worker = threading.Thread(target=write_comment)
                comment_worker.start()
                self.assertTrue(reservation_finished.wait(10))
                with session_factory() as db:
                    main._lock_active_user_reference(
                        db,
                        "agent-b",
                        label="Ticket assignee",
                    )
                    ticket = main._lock_ticket_record(db, "comment-race")
                    ticket.assignee_id = "agent-b"
                    db.commit()
                reassigned.set()
                comment_worker.join(10)
                self.assertFalse(comment_worker.is_alive())

            self.assertEqual(comment_outcome, [403])

            assignment_locked = threading.Event()
            allow_assignment_commit = threading.Event()
            time_lock_attempted = threading.Event()
            time_outcome = []

            def reassign_time_ticket():
                with session_factory() as db:
                    matched = db.query(TicketRecord).filter(
                        TicketRecord.id == "time-race"
                    ).update(
                        {TicketRecord.updated_at: TicketRecord.updated_at},
                        synchronize_session=False,
                    )
                    self.assertEqual(matched, 1)
                    ticket = db.get(TicketRecord, "time-race")
                    ticket.assignee_id = "agent-b"
                    db.flush()
                    assignment_locked.set()
                    if not allow_assignment_commit.wait(10):
                        raise AssertionError("time-entry race was not released")
                    db.commit()

            original_lock_ticket = main._lock_ticket_record

            def observed_ticket_lock(db, ticket_id):
                time_lock_attempted.set()
                return original_lock_ticket(db, ticket_id)

            def write_time_entry():
                if not assignment_locked.wait(10):
                    raise AssertionError("assignment lock was not acquired")
                with session_factory() as db:
                    actor = db.get(UserRecord, "agent-a")
                    try:
                        asyncio.run(main.create_time_entry(
                            TimeEntryCreate(
                                ticket_id="time-race",
                                description="Race evidence",
                                minutes=15,
                            ),
                            db,
                            actor,
                        ))
                        time_outcome.append(201)
                    except HTTPException as exc:
                        time_outcome.append(exc.status_code)

            with patch.object(
                main,
                "_lock_ticket_record",
                side_effect=observed_ticket_lock,
            ):
                assignment_worker = threading.Thread(target=reassign_time_ticket)
                time_worker = threading.Thread(target=write_time_entry)
                assignment_worker.start()
                time_worker.start()
                self.assertTrue(time_lock_attempted.wait(10))
                allow_assignment_commit.set()
                assignment_worker.join(10)
                time_worker.join(10)
                self.assertFalse(assignment_worker.is_alive())
                self.assertFalse(time_worker.is_alive())

            self.assertEqual(time_outcome, [403])
            with session_factory() as db:
                self.assertEqual(db.get(TicketRecord, "comment-race").assignee_id, "agent-b")
                self.assertEqual(db.get(TicketRecord, "time-race").assignee_id, "agent-b")
                self.assertEqual(db.query(TicketCommentRecord).count(), 0)
                self.assertEqual(db.query(TimeEntryRecord).count(), 0)
            engine.dispose()

    def test_concurrent_resolution_awards_serialize_per_user_and_stay_idempotent(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database_file:
            engine = create_engine(
                f"sqlite:///{database_file.name}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            session_factory = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            with session_factory() as db:
                db.add_all([
                    UserRecord(
                        id="award-agent",
                        name="Award Agent",
                        role="agent",
                        is_active=True,
                        impact_points=0,
                        momentum=0,
                        tier=1,
                    ),
                    TicketRecord(
                        id="award-ticket-a",
                        subject="Resolved A",
                        status="Resolved",
                        workflow_status="Resolved",
                        priority="P3",
                        assignee_id="award-agent",
                    ),
                    TicketRecord(
                        id="award-ticket-b",
                        subject="Resolved B",
                        status="Resolved",
                        workflow_status="Resolved",
                        priority="P3",
                        assignee_id="award-agent",
                    ),
                ])
                db.commit()

            barrier = threading.Barrier(2)

            def award(ticket_id):
                with session_factory() as db:
                    ticket = db.get(TicketRecord, ticket_id)
                    barrier.wait(timeout=10)
                    asyncio.run(main._check_resolution_and_award(ticket, db=db))

            with patch.object(
                main,
                "_broadcast_notification",
                new=AsyncMock(return_value=None),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(award, ticket_id)
                        for ticket_id in ("award-ticket-a", "award-ticket-b")
                    ]
                    for future in futures:
                        future.result(15)

            with session_factory() as db:
                user = db.get(UserRecord, "award-agent")
                tickets = db.query(TicketRecord).filter(
                    TicketRecord.id.in_(("award-ticket-a", "award-ticket-b"))
                ).all()
                self.assertEqual(user.impact_points, 31)
                self.assertEqual(user.momentum, 2)
                self.assertEqual(sum(ticket.points_awarded for ticket in tickets), 31)
                self.assertTrue(all(ticket.points_awarded_sent for ticket in tickets))
                self.assertTrue(all(ticket.resolved_by == "award-agent" for ticket in tickets))
                self.assertEqual(
                    db.query(RecognitionRecord).filter(
                        RecognitionRecord.user_id == "award-agent",
                        RecognitionRecord.recognition_key == "first_resolution",
                    ).count(),
                    1,
                )
                recognition_keys = [
                    row.recognition_key
                    for row in db.query(RecognitionRecord).filter(
                        RecognitionRecord.user_id == "award-agent"
                    ).all()
                ]
                self.assertEqual(len(recognition_keys), len(set(recognition_keys)))
            engine.dispose()

    def test_service_request_ticket_fields_require_dedicated_workflows(self):
        with self._demo_ticket_writes():
            patches = (
                {"status": "Resolved"},
                {"workflow_status": "Resolved"},
                {"ticket_type": "incident"},
                {"service_id": "service-inactive"},
                {"service_id": None},
            )
            responses = [
                self.client.patch(
                    "/tickets/ticket-delete-service",
                    headers=self.headers,
                    json=payload,
                )
                for payload in patches
            ]
            bulk_close = self.client.post(
                "/tickets/bulk",
                headers=self.headers,
                json={
                    "ticket_ids": ["ticket-delete-service"],
                    "action": "close",
                },
            )

        for response in (*responses, bulk_close):
            self.assertEqual(response.status_code, 409, response.text)
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "ticket-delete-service")
            self.assertEqual(ticket.status, "New")
            self.assertEqual(ticket.workflow_status, "New")
            self.assertEqual(ticket.ticket_type, "incident")
            self.assertIsNone(ticket.service_id)

    def test_problem_links_accept_only_incidents_and_block_type_bypasses(self):
        request_link = self.client.post(
            "/problems/problem-1/link/ticket-request-type",
            headers=self.headers,
        )
        incident_link = self.client.post(
            "/problems/problem-1/link/ticket-incident-link",
            headers=self.headers,
        )
        with self._demo_ticket_writes():
            type_change = self.client.patch(
                "/tickets/ticket-incident-link",
                headers=self.headers,
                json={"ticket_type": "request"},
            )
            request_conversion = self.client.post(
                "/service-requests",
                headers=self.headers,
                json={
                    "ticket_id": "ticket-incident-link",
                    "service_item_id": "service-active",
                },
            )

        self.assertEqual(request_link.status_code, 409, request_link.text)
        self.assertEqual(incident_link.status_code, 201, incident_link.text)
        self.assertEqual(type_change.status_code, 409, type_change.text)
        self.assertEqual(request_conversion.status_code, 409, request_conversion.text)
        unlinked = self.client.delete(
            "/problems/problem-1/link/ticket-incident-link",
            headers=self.headers,
        )
        relinked = self.client.post(
            "/problems/problem-1/link/ticket-incident-link",
            headers=self.headers,
        )
        self.assertEqual(unlinked.status_code, 200, unlinked.text)
        self.assertEqual(relinked.status_code, 201, relinked.text)
        with self.session_factory() as db:
            self.assertEqual(
                db.get(TicketRecord, "ticket-incident-link").ticket_type,
                "incident",
            )
            self.assertIsNone(
                db.query(ServiceRequestRecord).filter(
                    ServiceRequestRecord.ticket_id == "ticket-incident-link"
                ).first()
            )

    def test_resolution_history_cannot_be_reopened_or_converted_to_a_request(self):
        with self._demo_ticket_writes():
            history_conversion = self.client.post(
                "/service-requests",
                headers=self.headers,
                json={
                    "ticket_id": "ticket-resolution-history",
                    "service_item_id": "service-active",
                },
            )
            workflow_conversion = self.client.post(
                "/service-requests",
                headers=self.headers,
                json={
                    "ticket_id": "ticket-terminal-workflow",
                    "service_item_id": "service-active",
                },
            )
            reopen_status = self.client.patch(
                "/tickets/ticket-resolution-history",
                headers=self.headers,
                json={"status": "Open"},
            )
            reopen_workflow = self.client.patch(
                "/tickets/ticket-resolution-history",
                headers=self.headers,
                json={"workflow_status": "Open"},
            )

        for response in (
            history_conversion,
            workflow_conversion,
            reopen_status,
            reopen_workflow,
        ):
            self.assertEqual(response.status_code, 409, response.text)
        with self.session_factory() as db:
            ticket = db.get(TicketRecord, "ticket-resolution-history")
            self.assertEqual(ticket.status, "New")
            self.assertEqual(ticket.workflow_status, "New")
            self.assertEqual(ticket.points_awarded, 40)
            self.assertIsNotNone(ticket.resolved_at)

    def test_ticket_delete_fails_closed_on_retained_history_before_vectors(self):
        deleted_ids = []

        def record_vector_delete(db, ticket_id):
            self.assertIsNone(db.get(TicketRecord, ticket_id))
            deleted_ids.append(ticket_id)

        with (
            patch.object(main.settings_module, "is_production_mode", return_value=False),
            patch.object(
                main.ticket_vectors,
                "delete_ticket_documents",
                side_effect=record_vector_delete,
            ),
        ):
            retained = [
                self.client.delete(
                    f"/tickets/{ticket_id}",
                    headers=self.headers,
                )
                for ticket_id in (
                    "ticket-delete-problem",
                    "ticket-delete-change",
                    "ticket-delete-service",
                )
            ]
            deleted = self.client.delete(
                "/tickets/ticket-delete-free",
                headers=self.headers,
            )

        for response in retained:
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted_ids, ["ticket-delete-free"])
        with self.session_factory() as db:
            for ticket_id in (
                "ticket-delete-problem",
                "ticket-delete-change",
                "ticket-delete-service",
            ):
                self.assertIsNotNone(db.get(TicketRecord, ticket_id))

    def test_only_supported_operational_users_can_own_records(self):
        responses = (
            self.client.post(
                "/projects",
                headers=self.headers,
                json={"name": "Audited project", "key": "AUD", "lead_id": "auditor"},
            ),
            self.client.post(
                "/problems",
                headers=self.headers,
                json={"title": "Audited problem", "assigned_to": "auditor"},
            ),
            self.client.post(
                "/assets",
                headers=self.headers,
                json={
                    "name": "Audited asset",
                    "asset_type": "Hardware",
                    "owner_id": "auditor",
                },
            ),
        )
        for response in responses:
            self.assertEqual(response.status_code, 409, response.text)

    def test_asset_warranty_cannot_precede_purchase_on_create_or_partial_update(self):
        invalid_create = self.client.post(
            "/assets",
            headers=self.headers,
            json={
                "name": "Invalid warranty",
                "asset_type": "Hardware",
                "purchase_date": "2026-08-20T00:00:00Z",
                "warranty_expiry": "2026-08-19T00:00:00Z",
            },
        )
        valid = self.client.patch(
            "/assets/asset-1",
            headers=self.headers,
            json={
                "purchase_date": "2026-08-20T00:00:00Z",
                "warranty_expiry": "2027-08-20T00:00:00Z",
            },
        )
        invalid_purchase = self.client.patch(
            "/assets/asset-1",
            headers=self.headers,
            json={"purchase_date": "2028-01-01T00:00:00Z"},
        )
        invalid_warranty = self.client.patch(
            "/assets/asset-1",
            headers=self.headers,
            json={"warranty_expiry": "2026-08-19T00:00:00Z"},
        )

        self.assertEqual(invalid_create.status_code, 422, invalid_create.text)
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(invalid_purchase.status_code, 422, invalid_purchase.text)
        self.assertEqual(invalid_warranty.status_code, 422, invalid_warranty.text)

    def test_operational_payloads_reject_nul_and_invalid_asset_vocabularies(self):
        responses = (
            self.client.post(
                "/projects",
                headers=self.headers,
                json={"name": "bad\x00name", "key": "NUL"},
            ),
            self.client.post(
                "/problems",
                headers=self.headers,
                json={"title": "bad", "description": "bad\x00description"},
            ),
            self.client.post(
                "/assets",
                headers=self.headers,
                json={"name": "bad", "asset_type": "Cloud"},
            ),
            self.client.patch(
                "/assets/asset-1",
                headers=self.headers,
                json={"status": "Active"},
            ),
        )

        self.assertTrue(all(response.status_code == 422 for response in responses))


if __name__ == "__main__":
    unittest.main()
