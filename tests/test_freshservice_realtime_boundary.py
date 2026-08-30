import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    AIArtifactRecord,
    Base,
    ExternalActivityRecord,
    ExternalConversationRecord,
    ExternalUserRecord,
    SyncStateRecord,
    TicketCommentRecord,
    TicketRecord,
)
from app.backend import main, sync_worker, ticket_vectors
from app.backend.integrations import sync
from app.backend.schema import ExternalConversation, ExternalTicket


class _FreshserviceAdapter:
    provider_name = "freshservice"

    def __init__(self, tickets):
        self.tickets = tickets

    async def fetch_new_tickets(self, since=None):
        return self.tickets

    async def fetch_tickets_since(self, since=None):
        return self.tickets

    async def fetch_ticket_conversations(self, external_id, max_pages=None):
        ticket = next(item for item in self.tickets if item.external_id == external_id)
        return ticket.conversations

    async def fetch_ticket_details(self, external_id):
        return next(item for item in self.tickets if item.external_id == external_id)

    @staticmethod
    def rate_limit_snapshot():
        return {"total": 500, "remaining": 499, "used": 1}

    @staticmethod
    def should_pause_requests():
        return False


class FreshserviceRealtimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        # Match production SessionLocal semantics so repeated embedded
        # identities in one projection exercise the no-autoflush path.
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False)
        self.cutover = datetime.utcnow().replace(microsecond=0) - timedelta(hours=2)

    def tearDown(self):
        self.engine.dispose()

    def _ticket(self, conversation_at, *, conversation_id="conversation-1"):
        return ExternalTicket(
            external_id="42",
            subject="VPN unavailable",
            description="Initial report",
            reporter="requester-7",
            priority="P2",
            status="Open",
            assignee_id="agent-9",
            external_group_id="group-3",
            external_category="Network",
            updated_at=conversation_at,
            created_at=self.cutover - timedelta(days=30),
            conversations_loaded=True,
            conversations=[ExternalConversation(
                external_id=conversation_id,
                body="The customer added current diagnostic details.",
                author_id="requester-7",
                is_private=False,
                incoming=True,
                source=2,
                created_at=conversation_at,
                updated_at=conversation_at,
            )],
        )

    def _sync(self, adapter):
        with (
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "refresh_ticket_documents_if_indexed"),
            patch.object(sync.settings_module, "automation_enabled", return_value=True),
        ):
            return sync.sync_tickets_from_external(adapter)

    @staticmethod
    def _add_complete_route(
        db,
        *,
        ticket_id,
        created_at,
        pipeline_version,
        model,
    ):
        route = {
            "primary_group": "NETWORK_OPERATIONS",
            "secondary_group": None,
            "confidence": 0.91,
            "scope": "multiple_users",
            "affected_service": "corporate VPN",
            "failure_domain": "shared network failure",
            "reason": "Multiple users cannot establish the shared VPN connection.",
        }
        input_hash = ticket_id[0] * 64
        ticket = TicketRecord(
            id=ticket_id,
            binding_id="binding-1",
            external_source="freshservice",
            external_id=ticket_id,
            subject=f"Complete route for {ticket_id}",
            status="Open",
            ai_status="completed",
            ai_suggested_team=route["primary_group"],
            ai_secondary_team=route["secondary_group"],
            ai_routing_confidence=route["confidence"],
            ai_routing_scope=route["scope"],
            ai_affected_service=route["affected_service"],
            ai_failure_domain=route["failure_domain"],
            ai_routing_reason=route["reason"],
            ai_routing_input_hash=input_hash,
            created_at=created_at,
            external_created_at=created_at,
            external_updated_at=created_at,
        )
        db.add(ticket)
        db.flush()
        db.add(AIArtifactRecord(
            ticket_id=ticket.id,
            artifact="route",
            input_hash=input_hash,
            pipeline_version=pipeline_version,
            provider="custom",
            model=model,
            synthetic=False,
            content_hash=main._routing_payload_content_hash(route),
            active=True,
        ))
        return ticket

    def _add_hydration_ticket(
        self,
        db,
        *,
        ticket_id,
        binding_id,
        external_created_at,
        external_updated_at,
        requester_email="requester@shared.example",
    ):
        ticket = self._add_complete_route(
            db,
            ticket_id=ticket_id,
            created_at=external_created_at,
            pipeline_version="resolver-route-v1",
            model="resolver-model",
        )
        ticket.binding_id = binding_id
        ticket.external_id = ticket_id
        ticket.subject = "VPN unavailable"
        ticket.description = "Initial report"
        ticket.reporter = requester_email
        ticket.external_requester_email = requester_email
        ticket.external_created_at = external_created_at
        ticket.external_updated_at = external_updated_at
        ticket.ai_reasoning = "The shared VPN failure is supported by the report."
        ticket.summary = "The shared VPN is unavailable."
        ticket.recommended_solution = "Validate the shared VPN service."
        ticket.ai_source_hash = "s" * 64
        ticket.ai_pipeline_version = "analysis-v1"
        ticket.ai_model = "analysis-model"
        for artifact, marker in (
            ("triage", "t"),
            ("summary", "s"),
            ("resolution", "r"),
        ):
            db.add(AIArtifactRecord(
                ticket_id=ticket.id,
                artifact=artifact,
                input_hash="i" * 64,
                pipeline_version="analysis-v1",
                provider="custom",
                model="analysis-model",
                synthetic=False,
                content_hash=marker * 64,
                active=True,
            ))
        return ticket

    @staticmethod
    def _mark_ticket_indexed(db, ticket_id):
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS ticket_search_documents ("
            "source_type TEXT NOT NULL, source_id TEXT NOT NULL)"
        ))
        db.execute(
            text(
                "INSERT INTO ticket_search_documents (source_type, source_id) "
                "VALUES ('ticket', :source_id)"
            ),
            {"source_id": ticket_id},
        )

    def test_existing_bindings_default_disabled_and_seed_history_never_queues(self):
        historical = self._ticket(self.cutover - timedelta(days=1))
        result = self._sync(_FreshserviceAdapter([historical]))

        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertFalse(state.automatic_ai_enabled)
            self.assertIsNone(state.automatic_ai_generation)
            self.assertIsNone(state.automatic_ai_cutover_at)
            ticket = db.query(TicketRecord).one()
            self.assertIsNone(ticket.ai_status)
            self.assertIn("current diagnostic details", ticket.external_conversation_text)
            activity = db.query(ExternalActivityRecord).filter(
                ExternalActivityRecord.entity_type == "conversation"
            ).one()
            self.assertEqual(activity.acquisition_mode, "historical_seed")
            self.assertFalse(activity.automatic_ai_eligible)
            self.assertEqual(
                activity.eligibility_reason, "historical_seed_not_eligible"
            )

    def test_public_transcript_is_deterministically_bounded(self):
        historical = self._ticket(self.cutover - timedelta(days=1))
        historical.conversations = [
            ExternalConversation(
                external_id=f"conversation-{index:03d}",
                body=(f"message-{index:03d}-" + "x" * 4_100),
                author_id="requester-7",
                is_private=False,
                incoming=True,
                source=2,
                created_at=self.cutover - timedelta(days=2) + timedelta(minutes=index),
                updated_at=self.cutover - timedelta(days=2) + timedelta(minutes=index),
            )
            for index in range(60)
        ]

        projection_selects = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and any(
                f" from {table} " in normalized
                for table in (
                    "ticket_comments",
                    "external_activities",
                    "external_conversations",
                )
            ):
                projection_selects.append(normalized)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            self.assertEqual(
                self._sync(_FreshserviceAdapter([historical]))["errors"],
                0,
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        for table, limit in (
            ("ticket_comments", 2),
            ("external_activities", 3),
            ("external_conversations", 2),
        ):
            selects = [
                item for item in projection_selects
                if f" from {table} " in item
            ]
            self.assertLessEqual(len(selects), limit, (table, selects))
        with self.session_factory() as db:
            rendered = db.query(TicketRecord).one().external_conversation_text
            payload = json.loads(rendered)
            self.assertEqual(db.query(ExternalUserRecord).count(), 1)
            self.assertLessEqual(len(rendered.encode("utf-8")), 12_000)
            self.assertLessEqual(payload["selected_records"], 50)
            self.assertEqual(payload["total_records"], 60)
            self.assertGreater(payload["omitted_records"], 0)
            self.assertTrue(
                any(
                    item["body"]["body_truncated"]
                    for item in payload["conversations"]
                )
            )

    def test_post_cutover_reply_on_old_ticket_requires_manual_analysis(self):
        with self.session_factory() as db:
            state = SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.cutover,
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
                automatic_ai_enabled_by="admin",
            )
            db.add(state)
            db.commit()

        current = self._ticket(self.cutover + timedelta(minutes=1))
        result = self._sync(_FreshserviceAdapter([current]))

        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).one()
            self.assertIsNone(ticket.ai_status)
            activity = db.query(ExternalActivityRecord).filter(
                ExternalActivityRecord.entity_type == "conversation"
            ).one()
            self.assertFalse(activity.automatic_ai_eligible)
            self.assertEqual(
                activity.eligibility_reason,
                "ticket_created_before_lookback",
            )
            self.assertIsNone(activity.automatic_ai_generation)
            conversation = db.query(ExternalConversationRecord).one()
            self.assertEqual(conversation.author_external_id, "requester-7")
            comment = db.query(TicketCommentRecord).one()
            self.assertIsNone(comment.author_id)
            self.assertEqual(comment.external_author_id, "requester-7")

        second = self._sync(_FreshserviceAdapter([current]))
        self.assertEqual(second["errors"], 0)
        with self.session_factory() as db:
            self.assertEqual(
                db.query(ExternalActivityRecord).filter(
                    ExternalActivityRecord.entity_type == "conversation"
                ).count(),
                1,
            )

    def test_new_post_cutover_ticket_is_queued_during_background_sync(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.cutover,
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
                automatic_ai_enabled_by="admin",
            ))
            db.commit()

        received_at = self.cutover + timedelta(minutes=1)
        current = self._ticket(received_at)
        current.created_at = received_at
        current.updated_at = received_at
        current.conversations = []
        result = self._sync(_FreshserviceAdapter([current]))

        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).one()
            self.assertEqual(ticket.ai_status, "queued")
            self.assertEqual(
                set(ticket.ai_requested_artifacts.split(",")),
                {"triage", "summary", "route", "resolution"},
            )
            activity = db.query(ExternalActivityRecord).filter(
                ExternalActivityRecord.entity_type == "ticket"
            ).one()
            self.assertTrue(activity.automatic_ai_eligible)

    def test_private_post_cutover_note_is_stored_but_never_enters_ai_context(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.cutover,
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
            ))
            db.commit()

        private = self._ticket(self.cutover + timedelta(minutes=1))
        private.conversations[0].is_private = True
        result = self._sync(_FreshserviceAdapter([private]))

        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).one()
            self.assertIsNone(ticket.ai_status)
            self.assertNotIn("current diagnostic details", ticket.external_conversation_text)
            self.assertTrue(db.query(TicketCommentRecord).one().is_private)
            activity = db.query(ExternalActivityRecord).filter(
                ExternalActivityRecord.entity_type == "conversation"
            ).one()
            self.assertFalse(activity.automatic_ai_eligible)
            self.assertIsNone(activity.affected_artifacts)

    def test_public_to_private_transition_purges_ai_context_before_requeue(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.cutover,
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
            ))
            db.commit()

        public = self._ticket(self.cutover + timedelta(minutes=1))
        public.created_at = self.cutover + timedelta(minutes=1)
        adapter = _FreshserviceAdapter([public])
        self.assertEqual(self._sync(adapter)["errors"], 0)

        private = public.model_copy(deep=True)
        private.updated_at = self.cutover + timedelta(minutes=2)
        private.conversations[0].is_private = True
        private.conversations[0].body = "newly private diagnostic secret"
        private.conversations[0].updated_at = private.updated_at
        adapter.tickets = [private]
        self.assertEqual(self._sync(adapter)["errors"], 0)

        with self.session_factory() as db:
            ticket = db.query(TicketRecord).one()
            self.assertEqual(ticket.ai_status, "queued")
            self.assertNotIn("newly private diagnostic secret", ticket.external_conversation_text)
            self.assertNotIn("current diagnostic details", ticket.external_conversation_text)
            self.assertIn('"value_state":"removed"', ticket.external_conversation_text)
            self.assertTrue(db.query(TicketCommentRecord).one().is_private)

    def test_projection_failure_rolls_back_ticket_and_activity_together(self):
        current = self._ticket(self.cutover + timedelta(minutes=1))
        with (
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "_project_ticket_context", side_effect=RuntimeError),
        ):
            result = sync.sync_tickets_from_external(_FreshserviceAdapter([current]))

        self.assertEqual(result["errors"], 1)
        with self.session_factory() as db:
            self.assertEqual(db.query(TicketRecord).count(), 0)
            self.assertEqual(db.query(ExternalActivityRecord).count(), 0)

    def test_delayed_pre_cutover_reply_projects_but_does_not_queue(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.cutover,
                automatic_ai_enabled=True,
                automatic_ai_generation=3,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
            ))
            db.commit()

        delayed = self._ticket(self.cutover - timedelta(seconds=1))
        result = self._sync(_FreshserviceAdapter([delayed]))

        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).one()
            self.assertIsNone(ticket.ai_status)
            activity = db.query(ExternalActivityRecord).filter(
                ExternalActivityRecord.entity_type == "conversation"
            ).one()
            self.assertFalse(activity.automatic_ai_eligible)
            self.assertEqual(activity.eligibility_reason, "before_cutover")

    def test_future_provider_time_fails_closed(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.cutover,
                automatic_ai_enabled=True,
                automatic_ai_generation=4,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
            ))
            db.commit()

        future = self._ticket(datetime.utcnow() + timedelta(days=1))
        result = self._sync(_FreshserviceAdapter([future]))

        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).one()
            self.assertIsNone(ticket.ai_status)
            activity = db.query(ExternalActivityRecord).filter(
                ExternalActivityRecord.entity_type == "conversation"
            ).one()
            self.assertFalse(activity.automatic_ai_eligible)
            self.assertEqual(
                activity.eligibility_reason,
                "future_authoritative_activity_time",
            )

    def test_paused_generation_keeps_realtime_evidence_without_queueing(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.cutover,
                automatic_ai_enabled=False,
                automatic_ai_generation=5,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
                automatic_ai_paused_at=self.cutover + timedelta(minutes=1),
            ))
            db.commit()

        current = self._ticket(self.cutover + timedelta(minutes=2))
        result = self._sync(_FreshserviceAdapter([current]))

        self.assertEqual(result["errors"], 0)
        with self.session_factory() as db:
            self.assertIsNone(db.query(TicketRecord).one().ai_status)
            activity = db.query(ExternalActivityRecord).filter(
                ExternalActivityRecord.entity_type == "conversation"
            ).one()
            self.assertEqual(activity.acquisition_mode, "realtime")
            self.assertFalse(activity.automatic_ai_eligible)
            self.assertEqual(activity.eligibility_reason, "automatic_ai_paused")

    def test_paused_detail_description_change_invalidates_without_queueing(self):
        observed_at = self.cutover + timedelta(minutes=10)
        detail = self._ticket(observed_at)
        detail.external_id = "paused-detail"
        detail.created_at = self.cutover + timedelta(minutes=1)
        detail.description = "Hydrated description changed after list projection."
        detail.conversations = []
        adapter = _FreshserviceAdapter([detail])

        with self.session_factory() as db:
            state = SyncStateRecord(
                binding_id="binding-paused-detail",
                provider="freshservice",
                automatic_ai_enabled=False,
                automatic_ai_generation=5,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
                automatic_ai_paused_at=self.cutover + timedelta(minutes=5),
            )
            db.add(state)
            self._add_hydration_ticket(
                db,
                ticket_id=detail.external_id,
                binding_id=state.binding_id,
                external_created_at=detail.created_at,
                external_updated_at=detail.updated_at,
            )
            db.commit()

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                return_value=True,
            ):
                hydrated, errors, _state = sync._hydrate_freshservice_conversations(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=state.binding_id,
                    limit=1,
                )

            self.assertEqual((hydrated, errors), (1, 0))
            ticket = db.get(TicketRecord, detail.external_id)
            self.assertEqual(ticket.description, detail.description)
            self.assertEqual(ticket.ai_status, "stale")
            self.assertIsNone(ticket.ai_requested_artifacts)
            self.assertIsNone(ticket.ai_reasoning)
            self.assertIsNone(ticket.summary)
            self.assertIsNone(ticket.recommended_solution)
            self.assertIsNone(ticket.ai_suggested_team)
            self.assertEqual(
                db.query(AIArtifactRecord).filter_by(
                    ticket_id=ticket.id,
                    active=True,
                ).count(),
                0,
            )
            activity = db.query(ExternalActivityRecord).filter_by(
                ticket_id=ticket.id,
                entity_type="ticket_detail",
            ).one()
            self.assertFalse(activity.automatic_ai_eligible)
            self.assertEqual(activity.eligibility_reason, "automatic_ai_paused")
            self.assertEqual(
                set(activity.affected_artifacts.split(",")),
                {"triage", "summary", "route", "resolution"},
            )

    def test_never_enabled_requester_change_preserves_ai_artifacts(self):
        observed_at = self.cutover + timedelta(minutes=10)
        detail = self._ticket(observed_at)
        detail.external_id = "never-enabled-detail"
        detail.created_at = self.cutover + timedelta(minutes=1)
        detail.requester_email = "another-requester@example.invalid"
        detail.reporter = detail.requester_email
        detail.conversations = []
        adapter = _FreshserviceAdapter([detail])

        with self.session_factory() as db:
            state = SyncStateRecord(
                binding_id="binding-never-enabled-detail",
                provider="freshservice",
                automatic_ai_enabled=False,
            )
            db.add(state)
            self._add_hydration_ticket(
                db,
                ticket_id=detail.external_id,
                binding_id=state.binding_id,
                external_created_at=detail.created_at,
                external_updated_at=detail.updated_at,
            )
            db.commit()

            with (
                patch.object(
                    sync.settings_module,
                    "automation_enabled",
                    return_value=True,
                ),
            ):
                hydrated, errors, _state = sync._hydrate_freshservice_conversations(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=state.binding_id,
                    limit=1,
                )

            self.assertEqual((hydrated, errors), (1, 0))
            ticket = db.get(TicketRecord, detail.external_id)
            self.assertEqual(ticket.external_requester_email, detail.requester_email)
            self.assertEqual(ticket.ai_status, "completed")
            self.assertIsNone(ticket.ai_requested_artifacts)
            self.assertIsNotNone(ticket.ai_suggested_team)
            self.assertIsNotNone(ticket.ai_reasoning)
            self.assertIsNotNone(ticket.summary)
            self.assertIsNotNone(ticket.recommended_solution)
            self.assertEqual(
                {
                    artifact.artifact
                    for artifact in db.query(AIArtifactRecord).filter_by(
                        ticket_id=ticket.id,
                        active=True,
                    )
                },
                {"triage", "summary", "route", "resolution"},
            )
            self.assertEqual(
                db.query(ExternalActivityRecord).filter_by(
                    ticket_id=ticket.id,
                    entity_type="ticket_detail",
                ).count(),
                0,
            )

    def test_old_history_details_outside_cutover_or_lookback_never_queue(self):
        history_at = self.cutover - timedelta(days=90)
        details = []
        with self.session_factory() as db:
            state = SyncStateRecord(
                binding_id="binding-history-detail",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=6,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
                history_since_at=history_at - timedelta(days=1),
                history_until_at=history_at + timedelta(days=1),
                history_requested_at=self.cutover,
                history_requested_by="admin",
                history_complete=False,
            )
            db.add(state)
            for ticket_id, detail_updated_at in (
                ("history-before-cutover", self.cutover - timedelta(seconds=1)),
                ("history-outside-lookback", self.cutover + timedelta(minutes=1)),
            ):
                detail = self._ticket(detail_updated_at)
                detail.external_id = ticket_id
                detail.created_at = history_at
                detail.description = f"Hydrated historical description for {ticket_id}."
                detail.conversations = []
                details.append(detail)
                self._add_hydration_ticket(
                    db,
                    ticket_id=ticket_id,
                    binding_id=state.binding_id,
                    external_created_at=history_at,
                    external_updated_at=history_at,
                )
            db.commit()
            adapter = _FreshserviceAdapter(details)

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                return_value=True,
            ):
                hydrated, errors, _state = sync._hydrate_freshservice_conversations(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=state.binding_id,
                    limit=2,
                )

            self.assertEqual((hydrated, errors), (2, 0))
            activities = {
                activity.ticket_id: activity
                for activity in db.query(ExternalActivityRecord).filter_by(
                    entity_type="ticket_detail",
                )
            }
            self.assertEqual(
                activities["history-before-cutover"].eligibility_reason,
                "before_cutover",
            )
            self.assertEqual(
                activities["history-outside-lookback"].eligibility_reason,
                "ticket_created_before_lookback",
            )
            for ticket_id in activities:
                ticket = db.get(TicketRecord, ticket_id)
                self.assertEqual(ticket.ai_status, "stale")
                self.assertIsNone(ticket.ai_requested_artifacts)
                self.assertFalse(activities[ticket_id].automatic_ai_eligible)
                self.assertEqual(
                    db.query(AIArtifactRecord).filter_by(
                        ticket_id=ticket_id,
                        active=True,
                    ).count(),
                    0,
                )

    def test_indexed_detail_description_correction_refreshes_retrieval_evidence(self):
        observed_at = self.cutover + timedelta(minutes=10)
        detail = self._ticket(observed_at)
        detail.external_id = "indexed-description-detail"
        detail.created_at = self.cutover + timedelta(minutes=1)
        detail.description = "Authoritative hydrated description."
        detail.conversations = []
        adapter = _FreshserviceAdapter([detail])

        with self.session_factory() as db:
            state = SyncStateRecord(
                binding_id="binding-indexed-description",
                provider="freshservice",
                automatic_ai_enabled=False,
                automatic_ai_generation=7,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
                automatic_ai_paused_at=self.cutover + timedelta(minutes=5),
            )
            db.add(state)
            self._add_hydration_ticket(
                db,
                ticket_id=detail.external_id,
                binding_id=state.binding_id,
                external_created_at=detail.created_at,
                external_updated_at=detail.updated_at,
            )
            self._mark_ticket_indexed(db, detail.external_id)
            db.commit()

            with (
                patch.object(
                    ticket_vectors,
                    "_ticket_document_table_exists",
                    return_value=True,
                ),
                patch.object(
                    ticket_vectors,
                    "refresh_ticket_documents_background",
                    return_value=1,
                ) as refresh,
                patch.object(
                    sync.settings_module,
                    "automation_enabled",
                    return_value=True,
                ),
            ):
                hydrated, errors, _state = sync._hydrate_freshservice_conversations(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=state.binding_id,
                    limit=1,
                )

            self.assertEqual((hydrated, errors), (1, 0))
            refresh.assert_called_once()
            refreshed_ticket = refresh.call_args.args[1]
            self.assertEqual(refreshed_ticket.id, detail.external_id)
            self.assertEqual(refreshed_ticket.description, detail.description)

    def test_indexed_requester_change_does_not_churn_retrieval_evidence(self):
        observed_at = self.cutover + timedelta(minutes=10)
        detail = self._ticket(observed_at)
        detail.external_id = "indexed-context-detail"
        detail.created_at = self.cutover + timedelta(minutes=1)
        detail.requester_email = "another-requester@example.invalid"
        detail.reporter = detail.requester_email
        detail.conversations = []
        adapter = _FreshserviceAdapter([detail])

        with self.session_factory() as db:
            state = SyncStateRecord(
                binding_id="binding-indexed-context",
                provider="freshservice",
                automatic_ai_enabled=False,
            )
            db.add(state)
            self._add_hydration_ticket(
                db,
                ticket_id=detail.external_id,
                binding_id=state.binding_id,
                external_created_at=detail.created_at,
                external_updated_at=detail.updated_at,
            )
            self._mark_ticket_indexed(db, detail.external_id)
            db.commit()

            with (
                patch.object(
                    ticket_vectors,
                    "_ticket_document_table_exists",
                    return_value=True,
                ),
                patch.object(
                    ticket_vectors,
                    "refresh_ticket_documents_background",
                    return_value=1,
                ) as refresh,
                patch.object(
                    sync.settings_module,
                    "automation_enabled",
                    return_value=True,
                ),
            ):
                hydrated, errors, _state = sync._hydrate_freshservice_conversations(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=state.binding_id,
                    limit=1,
                )

            self.assertEqual((hydrated, errors), (1, 0))
            self.assertEqual(
                db.get(TicketRecord, detail.external_id).external_requester_email,
                detail.requester_email,
            )
            refresh.assert_not_called()

    def test_enable_action_creates_boundary_only_when_explicit(self):
        with self.session_factory() as db:
            state = sync.enable_automatic_ai(
                db,
                binding_id="binding-1",
                provider="freshservice",
                actor_id="admin",
                reason="approved realtime canary",
                expected_generation=0,
            )
            self.assertTrue(state.automatic_ai_enabled)
            self.assertEqual(state.automatic_ai_generation, 1)
            self.assertIsNotNone(state.automatic_ai_cutover_at)
            with self.assertRaisesRegex(ValueError, "already_enabled"):
                sync.enable_automatic_ai(
                    db,
                    binding_id="binding-1",
                    provider="freshservice",
                    actor_id="admin",
                    reason="must not silently move the boundary",
                    expected_generation=1,
                )

    def test_assignment_changes_preserve_route_but_category_changes_invalidate_it(self):
        observed_at = self.cutover + timedelta(minutes=1)
        external = self._ticket(observed_at)
        external.requester_email = "requester@shared.example"
        external.conversations = []
        route = {
            "primary_group": "NETWORK_OPERATIONS",
            "secondary_group": None,
            "confidence": 0.91,
            "scope": "multiple_users",
            "affected_service": "corporate VPN",
            "failure_domain": "shared network failure",
            "reason": "Multiple users cannot establish the shared VPN connection.",
        }
        with self.session_factory() as db:
            ticket = TicketRecord(
                id="local-42",
                binding_id="legacy",
                external_source="freshservice",
                external_id=external.external_id,
                subject=external.subject,
                description=external.description,
                reporter=external.reporter,
                priority=external.priority,
                status=external.status,
                workflow_status=external.status,
                external_assignee_id=external.assignee_id,
                external_group_id=external.external_group_id,
                external_requester_email=external.requester_email,
                external_category=external.external_category,
                external_subcategory=external.external_subcategory,
                external_item_category=external.external_item_category,
                external_updated_at=external.updated_at,
                external_created_at=external.created_at,
                ai_status="completed",
                ai_suggested_team=route["primary_group"],
                ai_secondary_team=route["secondary_group"],
                ai_routing_confidence=route["confidence"],
                ai_routing_scope=route["scope"],
                ai_affected_service=route["affected_service"],
                ai_failure_domain=route["failure_domain"],
                ai_routing_reason=route["reason"],
            )
            db.add(ticket)
            db.flush()
            main._record_ai_artifact(db, ticket, "route", route, "unused")
            db.commit()

            assignment_change = external.model_copy(update={
                "assignee_id": "agent-10",
                "external_group_id": "group-4",
                "updated_at": observed_at + timedelta(minutes=1),
            })
            sync._upsert_ticket(
                db,
                assignment_change,
                "freshservice",
                overwrite=True,
                binding_id="legacy",
            )
            ticket = db.get(TicketRecord, "local-42")
            self.assertEqual(ticket.ai_suggested_team, "NETWORK_OPERATIONS")
            self.assertTrue(main._artifact_is_current(db, ticket, "route"))

            category_change = assignment_change.model_copy(update={
                "external_category": "Software",
                "updated_at": observed_at + timedelta(minutes=2),
            })
            sync._upsert_ticket(
                db,
                category_change,
                "freshservice",
                overwrite=True,
                binding_id="legacy",
            )
            ticket = db.get(TicketRecord, "local-42")
            self.assertIsNone(ticket.ai_suggested_team)
            self.assertEqual(ticket.ai_status, "partial")
            self.assertFalse(
                db.query(AIArtifactRecord).filter_by(
                    ticket_id=ticket.id,
                    artifact="route",
                    active=True,
                ).count()
            )

    def test_category_change_merges_route_resolution_into_delayed_summary_retry(self):
        observed_at = self.cutover + timedelta(minutes=30)
        created_at = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)
        changed = self._ticket(observed_at).model_copy(update={
            "external_category": "Software",
            "created_at": created_at,
            "conversations_loaded": False,
            "conversations": [],
        })
        retry_at = datetime.utcnow().replace(microsecond=0) + timedelta(minutes=20)
        route = {
            "primary_group": "NETWORK_OPERATIONS",
            "secondary_group": None,
            "confidence": 0.91,
            "scope": "multiple_users",
            "affected_service": "corporate VPN",
            "failure_domain": "shared network failure",
            "reason": "Multiple users cannot establish the shared VPN connection.",
        }

        with self.session_factory() as db:
            state = SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=self.cutover,
                automatic_ai_enabled_at=self.cutover,
            )
            ticket = TicketRecord(
                id="category-change-retry",
                binding_id="binding-1",
                external_source="freshservice",
                external_id=changed.external_id,
                subject=changed.subject,
                description=changed.description,
                reporter=changed.reporter,
                status="Open",
                workflow_status="Open",
                priority=changed.priority,
                ticket_type="incident",
                external_assignee_id=changed.assignee_id,
                external_group_id=changed.external_group_id,
                external_category="Network",
                external_created_at=created_at,
                external_updated_at=self.cutover + timedelta(minutes=1),
                created_at=created_at,
                ai_reasoning="scope: multiple users; shared VPN failure",
                recommended_solution="{}",
                ai_status="queued",
                ai_requested_artifacts="summary",
                ai_attempts=2,
                ai_next_attempt_at=retry_at,
                ai_error="summary:provider_unavailable",
                ai_suggested_team=route["primary_group"],
                ai_secondary_team=route["secondary_group"],
                ai_routing_confidence=route["confidence"],
                ai_routing_scope=route["scope"],
                ai_affected_service=route["affected_service"],
                ai_failure_domain=route["failure_domain"],
                ai_routing_reason=route["reason"],
            )
            db.add_all([state, ticket])
            db.commit()

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                side_effect=lambda key, *_args: key in {
                    "AUTO_ROUTE_ENABLED",
                    "AUTO_RESOLVE_ENABLED",
                },
            ):
                action, _ = sync._apply_external_ticket(
                    db,
                    state=state,
                    ext=changed,
                    adapter=_FreshserviceAdapter([changed]),
                    overwrite=True,
                    binding_id="binding-1",
                )

            self.assertEqual(action, "updated")
            ticket = db.get(TicketRecord, "category-change-retry")
            self.assertEqual(ticket.ai_status, "queued")
            self.assertEqual(
                ticket.ai_requested_artifacts,
                "resolution,route,summary",
            )
            self.assertEqual(ticket.ai_attempts, 2)
            self.assertEqual(ticket.ai_next_attempt_at, retry_at)
            self.assertEqual(ticket.ai_error, "summary:provider_unavailable")
            self.assertIsNone(ticket.ai_suggested_team)
            self.assertIsNone(ticket.recommended_solution)

    def test_requester_change_does_not_invalidate_route(self):
        external = self._ticket(self.cutover + timedelta(minutes=1))
        external.requester_email = "requester@shared.example"
        existing = TicketRecord(
            id="business-context",
            subject=external.subject,
            description=external.description,
            reporter=external.reporter,
            priority=external.priority,
            ticket_type="incident",
            external_priority_code=external.external_priority_code,
            external_ticket_type_raw=external.ticket_type,
            external_category=external.external_category,
            external_subcategory=external.external_subcategory,
            external_item_category=external.external_item_category,
            external_requester_email=external.requester_email,
            external_assignee_id=external.assignee_id,
            external_group_id=external.external_group_id,
        )

        assignment_change = external.model_copy(update={
            "assignee_id": "agent-10",
            "external_group_id": "group-4",
        })
        self.assertEqual(
            sync._ticket_change_artifacts(existing, assignment_change),
            set(),
        )

        requester_change = assignment_change.model_copy(update={
            "requester_email": "another-requester@example.invalid",
        })
        self.assertEqual(sync._ticket_change_artifacts(existing, requester_change), set())

    def test_enabled_binding_queues_recent_four_week_gaps_newest_first(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.session_factory() as db:
            db.add_all([
                SyncStateRecord(
                    binding_id="binding-1",
                    provider="freshservice",
                    automatic_ai_enabled=True,
                    automatic_ai_generation=1,
                    automatic_ai_cutover_at=now,
                    automatic_ai_enabled_at=now,
                ),
                SyncStateRecord(
                    binding_id="binding-paused",
                    provider="freshservice",
                    automatic_ai_enabled=False,
                    automatic_ai_generation=2,
                    automatic_ai_cutover_at=now,
                    automatic_ai_enabled_at=now,
                ),
            ])
            for ticket_id, binding_id, age_days in (
                ("recent-a", "binding-1", 27),
                ("recent-b", "binding-1", 1),
                ("too-old", "binding-1", 29),
                ("paused", "binding-paused", 1),
            ):
                activity_at = now - timedelta(days=age_days)
                db.add(TicketRecord(
                    id=ticket_id,
                    binding_id=binding_id,
                    external_source="freshservice",
                    external_id=ticket_id,
                    subject=ticket_id,
                    created_at=activity_at,
                    external_created_at=activity_at,
                    external_updated_at=activity_at,
                ))
            db.add(TicketRecord(
                id="old-imported-today",
                binding_id="binding-1",
                external_source="freshservice",
                external_id="old-imported-today",
                subject="old-imported-today",
                created_at=now,
                external_created_at=now - timedelta(days=30),
                external_updated_at=now,
            ))
            db.commit()

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                side_effect=lambda key, *_args: key in {
                    "AUTO_TRIAGE_ENABLED",
                    "AUTO_SUMMARIZE_ENABLED",
                    "AUTO_ROUTE_ENABLED",
                    "AUTO_RESOLVE_ENABLED",
                },
            ):
                first = sync.queue_recent_automatic_ai(
                    db, now=now, batch_size=1
                )
                first_queued = {
                    ticket_id
                    for ticket_id in ("recent-a", "recent-b")
                    if db.get(TicketRecord, ticket_id).ai_status == "queued"
                }
                second = sync.queue_recent_automatic_ai(
                    db, now=now, batch_size=1
                )
                third = sync.queue_recent_automatic_ai(
                    db, now=now, batch_size=1
                )

            self.assertEqual(first, {"lookback_days": 28, "queued": 1})
            self.assertEqual(first_queued, {"recent-b"})
            self.assertEqual(second, {"lookback_days": 28, "queued": 1})
            self.assertEqual(third, {"lookback_days": 28, "queued": 0})
            for ticket_id in ("recent-a", "recent-b"):
                ticket = db.get(TicketRecord, ticket_id)
                self.assertEqual(ticket.ai_status, "queued")
                self.assertEqual(
                    set(ticket.ai_requested_artifacts.split(",")),
                    {"triage", "summary", "route", "resolution"},
                )
            self.assertIsNone(db.get(TicketRecord, "too-old").ai_status)
            self.assertIsNone(
                db.get(TicketRecord, "old-imported-today").ai_status
            )
            self.assertIsNone(db.get(TicketRecord, "paused").ai_status)

    def test_recent_scanner_repairs_stale_route_provenance_idempotently(self):
        now = datetime.utcnow().replace(microsecond=0)
        expected_pipeline = "routing-pipeline-v2"
        expected_model = "llm-provider-v1:current"
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            self._add_complete_route(
                db,
                ticket_id="recent-stale-pipeline",
                created_at=now - timedelta(days=1),
                pipeline_version="routing-pipeline-v1",
                model=expected_model,
            )
            self._add_complete_route(
                db,
                ticket_id="recent-stale-model",
                created_at=now - timedelta(days=1),
                pipeline_version=expected_pipeline,
                model="llm-provider-v1:retired",
            )
            self._add_complete_route(
                db,
                ticket_id="recent-current-route",
                created_at=now - timedelta(days=1),
                pipeline_version=expected_pipeline,
                model=expected_model,
            )
            db.commit()

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                side_effect=lambda key, *_args: key == "AUTO_ROUTE_ENABLED",
            ):
                first = sync.queue_recent_automatic_ai(
                    db,
                    now=now,
                    batch_size=5,
                    expected_pipeline_version=expected_pipeline,
                    expected_model=expected_model,
                )
                second = sync.queue_recent_automatic_ai(
                    db,
                    now=now,
                    batch_size=5,
                    expected_pipeline_version=expected_pipeline,
                    expected_model=expected_model,
                )

            self.assertEqual(first, {"lookback_days": 28, "queued": 2})
            self.assertEqual(second, {"lookback_days": 28, "queued": 0})
            for ticket_id in ("recent-stale-pipeline", "recent-stale-model"):
                ticket = db.get(TicketRecord, ticket_id)
                self.assertEqual(ticket.ai_status, "queued")
                self.assertEqual(ticket.ai_requested_artifacts, "route")
            current = db.get(TicketRecord, "recent-current-route")
            self.assertEqual(current.ai_status, "completed")
            self.assertIsNone(current.ai_requested_artifacts)

    def test_recent_scanner_batches_route_provenance_checks(self):
        now = datetime.utcnow().replace(microsecond=0)
        expected_pipeline = "routing-pipeline-v2"
        expected_model = "llm-provider-v1:current"
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            for index in range(8):
                self._add_complete_route(
                    db,
                    ticket_id=f"recent-current-batch-{index}",
                    created_at=now - timedelta(days=1),
                    pipeline_version=expected_pipeline,
                    model=expected_model,
                )
            db.commit()

            artifact_selects = []

            def capture(_connection, _cursor, statement, _parameters, _context, _many):
                normalized = " ".join(statement.lower().split())
                if normalized.startswith("select ai_artifact_records."):
                    artifact_selects.append(normalized)

            event.listen(self.engine, "before_cursor_execute", capture)
            try:
                with patch.object(
                    sync.settings_module,
                    "automation_enabled",
                    side_effect=lambda key, *_args: key in {
                        "AUTO_SUMMARIZE_ENABLED",
                        "AUTO_ROUTE_ENABLED",
                    },
                ):
                    result = sync.queue_recent_automatic_ai(
                        db,
                        now=now,
                        batch_size=8,
                        expected_pipeline_version=expected_pipeline,
                        expected_model=expected_model,
                    )
            finally:
                event.remove(self.engine, "before_cursor_execute", capture)

        self.assertEqual(result, {"lookback_days": 28, "queued": 8})
        self.assertLessEqual(len(artifact_selects), 1, artifact_selects)

    def test_recent_scanner_isolates_terminal_content_filter_by_artifact(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            db.add_all([
                TicketRecord(
                    id="policy-terminal",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="policy-terminal",
                    subject="Policy terminal",
                    ai_reasoning="current triage",
                    recommended_solution="{}",
                    ai_status="triage_completed",
                    ai_error="summary:content_filtered",
                    external_created_at=now - timedelta(days=1),
                    external_updated_at=now - timedelta(hours=2),
                ),
                TicketRecord(
                    id="eligible-gap",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="eligible-gap",
                    subject="Eligible gap",
                    external_created_at=now - timedelta(days=1),
                    external_updated_at=now - timedelta(hours=1),
                ),
            ])
            db.commit()

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                return_value=True,
            ):
                result = sync.queue_recent_automatic_ai(
                    db, now=now, batch_size=2
                )

            self.assertEqual(result, {"lookback_days": 28, "queued": 2})
            terminal = db.get(TicketRecord, "policy-terminal")
            self.assertEqual(terminal.ai_status, "queued")
            self.assertEqual(terminal.ai_requested_artifacts, "route")
            self.assertEqual(terminal.ai_error, "summary:content_filtered")
            eligible = db.get(TicketRecord, "eligible-gap")
            self.assertEqual(eligible.ai_status, "queued")
            self.assertIn("summary", eligible.ai_requested_artifacts.split(","))

    def test_terminal_summary_rows_cannot_starve_older_real_ai_gaps(self):
        """Regress the dev failure where a bounded newest-first scan never advanced.

        A terminal summary outcome intentionally keeps ``summary`` empty. The
        SQL prefilter must pair that gap with summary eligibility instead of
        repeatedly spending the only scan slot on a ticket whose remaining
        artifacts are already current.
        """
        now = datetime.utcnow().replace(microsecond=0)
        expected_pipeline = "routing-pipeline-v2"
        expected_model = "llm-provider-v1:current"
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            blockers = []
            for index in range(5):
                blocker = self._add_complete_route(
                    db,
                    ticket_id=f"terminal-summary-blocker-{index}",
                    created_at=now - timedelta(hours=index + 1),
                    pipeline_version=expected_pipeline,
                    model=expected_model,
                )
                blocker.ai_status = "triage_completed"
                blocker.ai_reasoning = "Current triage"
                blocker.summary = None
                blocker.recommended_solution = "Current resolution plan"
                blocker.ai_error = "summary:content_filtered"
                blockers.append(blocker)
            db.add(TicketRecord(
                id="older-real-gap",
                binding_id="binding-1",
                external_source="freshservice",
                external_id="older-real-gap",
                subject="Older ticket that genuinely needs AI",
                status="Open",
                external_created_at=now - timedelta(days=2),
                external_updated_at=now - timedelta(days=2),
            ))
            db.commit()

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                return_value=True,
            ):
                result = sync.queue_recent_automatic_ai(
                    db,
                    now=now,
                    batch_size=1,
                    expected_pipeline_version=expected_pipeline,
                    expected_model=expected_model,
                )

            self.assertEqual(result, {"lookback_days": 28, "queued": 1})
            queued = db.get(TicketRecord, "older-real-gap")
            self.assertEqual(queued.ai_status, "queued")
            self.assertEqual(
                set(queued.ai_requested_artifacts.split(",")),
                {"triage", "summary", "route", "resolution"},
            )
            for blocker in blockers:
                db.refresh(blocker)
                self.assertEqual(blocker.ai_status, "triage_completed")
                self.assertIsNone(blocker.ai_requested_artifacts)
                self.assertEqual(blocker.ai_error, "summary:content_filtered")

    def test_route_content_filter_does_not_block_missing_triage_and_summary(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            db.add(TicketRecord(
                id="route-policy-terminal",
                binding_id="binding-1",
                external_source="freshservice",
                external_id="route-policy-terminal",
                subject="Missing independent analysis",
                recommended_solution="{}",
                ai_status="partial",
                ai_error="route:content_filtered",
                external_created_at=now - timedelta(days=1),
                external_updated_at=now - timedelta(hours=1),
            ))
            db.commit()

            with patch.object(
                sync.settings_module,
                "automation_enabled",
                side_effect=lambda key, *_args: key in {
                    "AUTO_TRIAGE_ENABLED",
                    "AUTO_SUMMARIZE_ENABLED",
                    "AUTO_ROUTE_ENABLED",
                },
            ):
                result = sync.queue_recent_automatic_ai(
                    db,
                    now=now,
                    batch_size=1,
                )

            self.assertEqual(result, {"lookback_days": 28, "queued": 1})
            ticket = db.get(TicketRecord, "route-policy-terminal")
            self.assertEqual(ticket.ai_status, "queued")
            self.assertEqual(
                set(ticket.ai_requested_artifacts.split(",")),
                {"triage", "summary"},
            )
            self.assertNotIn("route", ticket.ai_requested_artifacts.split(","))
            self.assertEqual(ticket.ai_error, "route:content_filtered")

    def test_active_routing_backlog_requires_explicit_opt_in_and_is_staged(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            db.add_all([
                TicketRecord(
                    id="old-active",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="old-active",
                    subject="Old active ticket",
                    status="Open",
                    external_created_at=now - timedelta(days=90),
                    external_updated_at=now - timedelta(days=1),
                ),
                TicketRecord(
                    id="old-closed",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="old-closed",
                    subject="Old closed ticket",
                    status="Closed",
                    external_created_at=now - timedelta(days=90),
                    external_updated_at=now,
                ),
                TicketRecord(
                    id="old-source-routed",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="old-source-routed",
                    subject="Old ticket with authoritative source route",
                    status="Open",
                    external_category="Hardware - Computers",
                    external_created_at=now - timedelta(days=90),
                    external_updated_at=now - timedelta(days=1),
                ),
                TicketRecord(
                    id="old-group-routed",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="old-group-routed",
                    external_group_id="group-42",
                    subject="Old ticket already assigned to a provider group",
                    status="Open",
                    external_created_at=now - timedelta(days=90),
                    external_updated_at=now - timedelta(days=1),
                ),
            ])
            db.commit()

            with (
                patch.dict(
                    "os.environ",
                    {"AI_ACTIVE_ROUTING_BACKLOG_ENABLED": "false"},
                    clear=False,
                ),
                patch.object(sync.settings_module, "automation_enabled", return_value=True),
            ):
                self.assertEqual(
                    sync.queue_active_routing_backlog(db),
                    {"enabled": False, "queued": 0},
                )

            with (
                patch.dict(
                    "os.environ",
                    {"AI_ACTIVE_ROUTING_BACKLOG_ENABLED": "true"},
                    clear=False,
                ),
                patch.object(sync.settings_module, "automation_enabled", return_value=True),
            ):
                self.assertEqual(
                    sync.queue_active_routing_backlog(db),
                    {"enabled": True, "queued": 3},
                )

            active = db.get(TicketRecord, "old-active")
            self.assertEqual(active.ai_status, "queued")
            self.assertEqual(
                set(active.ai_requested_artifacts.split(",")),
                {"triage", "route"},
            )
            self.assertIsNone(db.get(TicketRecord, "old-closed").ai_status)
            for ticket_id in ("old-source-routed", "old-group-routed"):
                ticket = db.get(TicketRecord, ticket_id)
                self.assertEqual(ticket.ai_status, "queued")
                self.assertEqual(
                    set(ticket.ai_requested_artifacts.split(",")),
                    {"triage", "route"},
                )

    def test_active_routing_backlog_repairs_stale_route_provenance_idempotently(self):
        now = datetime.utcnow().replace(microsecond=0)
        expected_pipeline = "routing-pipeline-v2"
        expected_model = "llm-provider-v1:current"
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            self._add_complete_route(
                db,
                ticket_id="backlog-stale-pipeline",
                created_at=now - timedelta(days=90),
                pipeline_version="routing-pipeline-v1",
                model=expected_model,
            )
            self._add_complete_route(
                db,
                ticket_id="backlog-stale-model",
                created_at=now - timedelta(days=90),
                pipeline_version=expected_pipeline,
                model="llm-provider-v1:retired",
            )
            self._add_complete_route(
                db,
                ticket_id="backlog-current-route",
                created_at=now - timedelta(days=90),
                pipeline_version=expected_pipeline,
                model=expected_model,
            )
            db.commit()

            with (
                patch.dict(
                    "os.environ",
                    {"AI_ACTIVE_ROUTING_BACKLOG_ENABLED": "true"},
                    clear=False,
                ),
                patch.object(
                    sync.settings_module,
                    "automation_enabled",
                    side_effect=lambda key, *_args: key == "AUTO_ROUTE_ENABLED",
                ),
            ):
                first = sync.queue_active_routing_backlog(
                    db,
                    batch_size=5,
                    expected_pipeline_version=expected_pipeline,
                    expected_model=expected_model,
                )
                second = sync.queue_active_routing_backlog(
                    db,
                    batch_size=5,
                    expected_pipeline_version=expected_pipeline,
                    expected_model=expected_model,
                )

            self.assertEqual(first, {"enabled": True, "queued": 2})
            self.assertEqual(second, {"enabled": True, "queued": 0})
            for ticket_id in ("backlog-stale-pipeline", "backlog-stale-model"):
                ticket = db.get(TicketRecord, ticket_id)
                self.assertEqual(ticket.ai_status, "queued")
                self.assertEqual(ticket.ai_requested_artifacts, "route")
            current = db.get(TicketRecord, "backlog-current-route")
            self.assertEqual(current.ai_status, "completed")
            self.assertIsNone(current.ai_requested_artifacts)

    def test_active_routing_backlog_prioritizes_stale_recovery(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="binding-1",
                provider="freshservice",
                automatic_ai_enabled=True,
                automatic_ai_generation=1,
                automatic_ai_cutover_at=now,
                automatic_ai_enabled_at=now,
            ))
            db.add_all([
                TicketRecord(
                    id="newer-gap",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="newer-gap",
                    subject="Newer ticket missing routing",
                    status="Open",
                    external_created_at=now - timedelta(days=30),
                    external_updated_at=now,
                ),
                TicketRecord(
                    id="older-stale",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="older-stale",
                    subject="Older stale ticket with prior output",
                    status="Open",
                    external_created_at=now - timedelta(days=90),
                    external_updated_at=now - timedelta(days=60),
                    ai_status="stale",
                    ai_reasoning="Prior triage output",
                    ai_suggested_team="SOFTWARE_ENGINEERING",
                ),
            ])
            db.commit()

            with (
                patch.dict(
                    "os.environ",
                    {"AI_ACTIVE_ROUTING_BACKLOG_ENABLED": "true"},
                    clear=False,
                ),
                patch.object(sync.settings_module, "automation_enabled", return_value=True),
            ):
                result = sync.queue_active_routing_backlog(db, batch_size=1)

            self.assertEqual(result, {"enabled": True, "queued": 1})
            stale = db.get(TicketRecord, "older-stale")
            self.assertEqual(stale.ai_status, "queued")
            self.assertEqual(
                set(stale.ai_requested_artifacts.split(",")),
                {"route"},
            )
            self.assertIsNone(db.get(TicketRecord, "newer-gap").ai_status)

    def test_worker_processes_recent_external_gap_without_manual_queueing(self):
        now = datetime.utcnow().replace(microsecond=0)
        with self.session_factory() as db:
            db.add_all([
                SyncStateRecord(
                    binding_id="binding-1",
                    provider="freshservice",
                    automatic_ai_enabled=True,
                    automatic_ai_generation=1,
                    automatic_ai_cutover_at=now,
                    automatic_ai_enabled_at=now,
                ),
                TicketRecord(
                    id="recent-worker-gap",
                    binding_id="binding-1",
                    external_source="freshservice",
                    external_id="recent-worker-gap",
                    subject="Needs background analysis",
                    created_at=now - timedelta(days=1),
                    external_created_at=now - timedelta(days=1),
                ),
            ])
            db.commit()

        process = AsyncMock()
        with (
            patch.object(sync_worker, "SessionLocal", self.session_factory),
            patch.object(sync_worker, "_refresh_admin_settings"),
            patch.object(
                sync_worker.settings_module,
                "automation_enabled",
                side_effect=lambda key, *_args: key in {
                    "AUTO_TRIAGE_ENABLED",
                    "AUTO_SUMMARIZE_ENABLED",
                    "AUTO_RESOLVE_ENABLED",
                },
            ),
            patch.object(main, "_auto_process", new=process),
        ):
            sync_worker._auto_triage_job()

        process.assert_awaited_once()
        self.assertEqual(process.await_args.args[0].id, "recent-worker-gap")
        self.assertTrue(process.await_args.kwargs["force"])


if __name__ == "__main__":
    unittest.main()
