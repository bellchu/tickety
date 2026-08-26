import asyncio
import io
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main, sync_worker, ticket_vectors
from app.backend.database import (
    Base,
    ProblemRecord,
    ProblemTicketLinkRecord,
    SyncStateRecord,
    TicketRecord,
    UserRecord,
)
from app.backend.integrations import sync
from app.backend.integrations.freshservice import FreshserviceAdapter
from app.backend.integrations.jira import JiraAdapter
from app.backend.schema import ExternalTicket


def _external_ticket(**overrides) -> ExternalTicket:
    values = {
        "external_id": "provider-1",
        "subject": "Valid provider ticket",
        "description": "Bounded requester content",
        "reporter": "requester@example.test",
        "priority": "P3",
        "status": "Open",
        "updated_at": datetime(2026, 7, 12, 12, 0, 0),
    }
    values.update(overrides)
    return ExternalTicket(**values)


class WorkerSourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        UserRecord.__table__.create(self.engine)
        TicketRecord.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _run_worker(self, process, *, automation=True):
        with (
            patch.object(sync_worker, "SessionLocal", self.session_factory),
            patch.object(
                sync_worker.settings_module,
                "is_production_mode",
                return_value=True,
            ),
            patch.object(
                sync_worker.settings_module,
                "automation_enabled",
                return_value=automation,
            ),
            patch.object(main, "_auto_process", new=process),
        ):
            sync_worker._auto_triage_job()

    def test_implicit_gap_scan_only_selects_internal_manual_tickets(self):
        with self.session_factory() as db:
            db.add_all([
                TicketRecord(
                    id="manual",
                    subject="Internal manual ticket",
                    external_source="manual",
                ),
                TicketRecord(
                    id="external",
                    subject="Unreviewed provider ticket",
                    external_source="freshservice",
                ),
                TicketRecord(
                    id="portal",
                    subject="Anonymous portal ticket",
                    external_source="portal",
                ),
            ])
            db.commit()

        processed = []

        async def capture(ticket, *_args, **_kwargs):
            processed.append(ticket.id)

        self._run_worker(AsyncMock(side_effect=capture))
        self.assertEqual(processed, ["manual"])

    def test_explicit_queue_processes_external_and_portal_tickets(self):
        with self.session_factory() as db:
            db.add_all([
                TicketRecord(
                    id="external-queued",
                    subject="Reviewed provider ticket",
                    external_source="freshservice",
                    ai_status="queued",
                    ai_requested_artifacts="triage",
                ),
                TicketRecord(
                    id="portal-queued",
                    subject="Reviewed portal ticket",
                    external_source="portal",
                    ai_status="queued",
                    ai_requested_artifacts="triage",
                ),
            ])
            db.commit()

        processed = []

        async def capture(ticket, *_args, **kwargs):
            processed.append((ticket.id, kwargs.get("force")))

        self._run_worker(AsyncMock(side_effect=capture), automation=False)
        self.assertCountEqual(
            processed,
            [("external-queued", True), ("portal-queued", True)],
        )


class ExternalPersistenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_sync_persistence_does_not_refresh_shared_rag_documents(self):
        class Adapter:
            provider_name = "freshservice"

            async def fetch_new_tickets(self, since=None):
                return [_external_ticket()]

        with (
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "refresh_ticket_documents_background") as refresh,
        ):
            result = sync.sync_tickets_from_external(Adapter())

        self.assertEqual(result, {"new": 1, "updated": 0, "errors": 0})
        refresh.assert_not_called()
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).one()
            self.assertEqual(ticket.external_source, "freshservice")

    def test_comment_only_evidence_does_not_promote_external_ticket_document(self):
        ticket = TicketRecord(
            id="comment-only-ticket",
            subject="Unreviewed provider ticket",
            external_source="freshservice",
        )
        with self.session_factory() as db:
            db.execute(text(
                "CREATE TABLE ticket_search_documents "
                "(source_type TEXT, source_id TEXT, ticket_id TEXT)"
            ))
            # A reviewed comment is evidence for this ticket, but it must not
            # authorize provider subject/description as ticket evidence.
            db.execute(text(
                "INSERT INTO ticket_search_documents (source_type, source_id, ticket_id) "
                "VALUES ('comment', 'comment-1', :ticket_id)"
            ), {"ticket_id": ticket.id})
            db.commit()

            with (
                patch.object(ticket_vectors, "_ticket_document_table_exists", return_value=True),
                patch.object(ticket_vectors, "refresh_ticket_documents_background") as refresh,
            ):
                changed = ticket_vectors.refresh_ticket_documents_if_indexed(db, ticket)

        self.assertEqual(changed, 0)
        refresh.assert_not_called()

    def test_metadata_only_provider_update_refreshes_promoted_ticket(self):
        with self.session_factory() as db:
            existing = TicketRecord(
                id="promoted-ticket",
                subject="Valid provider ticket",
                description="Bounded requester content",
                reporter="requester@example.test",
                priority="P3",
                status="Open",
                workflow_status="Open",
                ticket_type="incident",
                external_source="freshservice",
                external_id="provider-1",
                external_status="Open",
            )
            db.add(existing)
            db.commit()

            with patch.object(sync, "refresh_ticket_documents_if_indexed") as refresh:
                action, ticket = sync._upsert_ticket(
                    db,
                    _external_ticket(ticket_type="service_request"),
                    "freshservice",
                    overwrite=True,
                )

            self.assertEqual(action, "updated")
            self.assertEqual(ticket.priority, "P3")
            self.assertEqual(ticket.ticket_type, "service_request")
            refresh.assert_called_once_with(db, ticket)

    def test_provider_reopen_clears_live_resolution_in_both_update_modes(self):
        resolved_at = datetime(2026, 7, 10, 9, 0, 0)
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite), self.session_factory() as db:
                provider_id = f"provider-reopen-{overwrite}"
                ticket = TicketRecord(
                    id=f"reopened-{overwrite}",
                    subject="Previously resolved incident",
                    description="Provider-owned content",
                    reporter="requester@example.test",
                    priority="P3",
                    status="Closed",
                    workflow_status="Closed",
                    ticket_type="incident",
                    external_source="freshservice",
                    external_id=provider_id,
                    external_status="Resolved",
                    external_resolved_at=resolved_at,
                    resolved_at=resolved_at,
                )
                db.add(ticket)
                db.commit()

                action, reopened = sync._upsert_ticket(
                    db,
                    _external_ticket(
                        external_id=provider_id,
                        status="Open",
                        resolved_at=None,
                        updated_at=resolved_at + timedelta(hours=1),
                    ),
                    "freshservice",
                    overwrite=overwrite,
                )

                self.assertEqual(action, "updated")
                self.assertEqual(reopened.status, "Open")
                self.assertEqual(reopened.workflow_status, "Open")
                self.assertEqual(reopened.external_status, "Open")
                self.assertIsNone(reopened.external_resolved_at)
                self.assertIsNone(reopened.resolved_at)

    def test_authoritative_provider_update_propagates_removed_deadlines(self):
        old_due = datetime(2026, 7, 14, 9, 0, 0)
        old_response_due = datetime(2026, 7, 13, 9, 0, 0)
        with self.session_factory() as db:
            db.add(TicketRecord(
                id="deadline-removed",
                subject="Provider deadline changed",
                description="Provider-owned content",
                reporter="requester@example.test",
                priority="P3",
                status="Open",
                workflow_status="Open",
                ticket_type="incident",
                external_source="freshservice",
                external_id="provider-deadline",
                external_status="Open",
                external_due_by=old_due,
                external_fr_due_by=old_response_due,
                due_by=old_due,
                resolution_due_at=old_due,
                response_due_at=old_response_due,
            ))
            db.commit()

            action, ticket = sync._upsert_ticket(
                db,
                _external_ticket(
                    external_id="provider-deadline",
                    due_by=None,
                    fr_due_by=None,
                    updated_at=old_due + timedelta(hours=1),
                ),
                "freshservice",
                overwrite=True,
            )

            self.assertEqual(action, "updated")
            for field in (
                "external_due_by", "external_fr_due_by", "due_by",
                "resolution_due_at", "response_due_at",
            ):
                self.assertIsNone(getattr(ticket, field), field)

    def test_provider_cannot_reclassify_linked_incident_as_a_request(self):
        with self.session_factory() as db:
            ticket = TicketRecord(
                id="linked-incident",
                subject="Incident evidence",
                reporter="requester@example.test",
                priority="P3",
                status="Open",
                workflow_status="Open",
                ticket_type="incident",
                external_source="freshservice",
                external_id="provider-1",
                external_status="Open",
            )
            problem = ProblemRecord(
                id="problem-1",
                title="Recurring provider incident",
                status="Under Investigation",
            )
            db.add_all([ticket, problem])
            db.flush()
            db.add(ProblemTicketLinkRecord(
                problem_id=problem.id,
                ticket_id=ticket.id,
            ))
            db.commit()

            with self.assertRaisesRegex(
                RuntimeError,
                "unlink it before synchronization",
            ):
                sync._upsert_ticket(
                    db,
                    _external_ticket(ticket_type=" SeRvIcE_ReQuEsT "),
                    "freshservice",
                    overwrite=True,
                )

            db.refresh(ticket)
            self.assertEqual(ticket.ticket_type, "incident")

    def test_problem_link_and_provider_type_transition_are_serialized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(
                f"sqlite:///{temp_dir}/problem-type-race.db",
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            session_factory = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            try:
                for index in range(8):
                    ticket_id = f"race-ticket-{index}"
                    problem_id = f"race-problem-{index}"
                    with session_factory() as db:
                        db.add_all([
                            TicketRecord(
                                id=ticket_id,
                                subject="Incident evidence",
                                reporter="requester@example.test",
                                status="Open",
                                workflow_status="Open",
                                ticket_type="incident",
                                external_source="freshservice",
                                external_id=f"provider-{index}",
                                external_status="Open",
                            ),
                            ProblemRecord(
                                id=problem_id,
                                title="Concurrent problem evidence",
                                status="Under Investigation",
                            ),
                        ])
                        db.commit()

                    barrier = threading.Barrier(2)

                    def transition_type():
                        with session_factory() as db:
                            barrier.wait(timeout=10)
                            try:
                                sync._upsert_ticket(
                                    db,
                                    _external_ticket(
                                        external_id=f"provider-{index}",
                                        ticket_type="service_request",
                                    ),
                                    "freshservice",
                                    overwrite=True,
                                )
                                return "type_changed"
                            except RuntimeError:
                                return "type_blocked"

                    def link_problem():
                        with session_factory() as db:
                            barrier.wait(timeout=10)
                            try:
                                asyncio.run(main.link_ticket_to_problem(
                                    problem_id,
                                    ticket_id,
                                    db,
                                ))
                                return "linked"
                            except HTTPException as exc:
                                return exc.status_code

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        results = [
                            future.result(timeout=30)
                            for future in (
                                executor.submit(transition_type),
                                executor.submit(link_problem),
                            )
                        ]
                    self.assertIn(
                        sorted(results, key=str),
                        [
                            sorted(["type_changed", 409], key=str),
                            sorted(["type_blocked", "linked"], key=str),
                        ],
                    )

                    with session_factory() as db:
                        ticket = db.get(TicketRecord, ticket_id)
                        linked = db.query(ProblemTicketLinkRecord.id).filter(
                            ProblemTicketLinkRecord.ticket_id == ticket_id
                        ).first()
                        self.assertFalse(
                            ticket.ticket_type != "incident" and linked is not None
                        )
            finally:
                engine.dispose()


class ProviderParserIsolationTests(unittest.TestCase):
    def test_freshservice_valid_malformed_valid_is_isolated(self):
        adapter = FreshserviceAdapter()
        records = [
            {"id": 1, "subject": "First", "description_text": "valid"},
            {
                "id": 2,
                "subject": "x" * 501,
                "description_text": "Poison marker must not be logged",
            },
            {"id": 3, "subject": "Third", "description_text": "valid"},
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            parsed = adapter._parse_ticket_batch(records)

        self.assertEqual([ticket.external_id for ticket in parsed], ["1", "3"])
        self.assertEqual(
            output.getvalue().strip(),
            "[External] Freshservice ticket parse skipped kind=ValidationError",
        )

    def test_jira_valid_malformed_valid_is_isolated(self):
        adapter = JiraAdapter()

        def issue(key, summary, description):
            return {
                "key": key,
                "fields": {
                    "summary": summary,
                    "description": description,
                    "priority": {"name": "Medium"},
                    "status": {"name": "Open"},
                    "reporter": {"emailAddress": "requester@example.test"},
                },
            }

        records = [
            issue("IT-1", "First", "valid"),
            issue("IT-2", "x" * 501, "Poison marker must not be logged"),
            issue("IT-3", "Third", "valid"),
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            parsed = adapter._parse_issue_batch(records)

        self.assertEqual([ticket.external_id for ticket in parsed], ["IT-1", "IT-3"])
        self.assertEqual(
            output.getvalue().strip(),
            "[Jira] ticket parse skipped kind=ValidationError",
        )


class ExternalTicketBoundsTests(unittest.TestCase):
    def test_all_external_text_and_identifier_fields_are_bounded(self):
        field_limits = {
            "external_id": 255,
            "subject": 500,
            "reporter": 320,
            "priority": 32,
            "status": 120,
            "assignee_id": 255,
            "ticket_type": 120,
            "requester_email": 320,
            "external_workspace_id": 255,
            "url": 2_048,
        }
        for field, limit in field_limits.items():
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    _external_ticket(**{field: "x" * (limit + 1)})

    def test_external_description_is_lossless_beyond_the_old_projection_limit(self):
        description = "x" * 150_000
        self.assertEqual(_external_ticket(description=description).description, description)

    def test_required_external_identifiers_and_labels_cannot_be_empty(self):
        for field in ("external_id", "subject", "priority", "status"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    _external_ticket(**{field: ""})


if __name__ == "__main__":
    unittest.main()
