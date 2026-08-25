import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import (
    Base,
    ExternalActivityRecord,
    ExternalConversationRecord,
    SyncStateRecord,
    TicketCommentRecord,
    TicketRecord,
)
from app.backend import main, sync_worker
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


class FreshserviceRealtimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
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

        self.assertEqual(
            self._sync(_FreshserviceAdapter([historical]))["errors"],
            0,
        )
        with self.session_factory() as db:
            rendered = db.query(TicketRecord).one().external_conversation_text
            payload = json.loads(rendered)
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
                {"triage", "route"},
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

    def test_enabled_binding_queues_recent_seven_day_gaps_in_bounded_sweeps(self):
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
                ("recent-a", "binding-1", 6),
                ("recent-b", "binding-1", 1),
                ("too-old", "binding-1", 8),
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
                second = sync.queue_recent_automatic_ai(
                    db, now=now, batch_size=1
                )
                third = sync.queue_recent_automatic_ai(
                    db, now=now, batch_size=1
                )

            self.assertEqual(first, {"lookback_days": 7, "queued": 1})
            self.assertEqual(second, {"lookback_days": 7, "queued": 1})
            self.assertEqual(third, {"lookback_days": 7, "queued": 0})
            for ticket_id in ("recent-a", "recent-b"):
                ticket = db.get(TicketRecord, ticket_id)
                self.assertEqual(ticket.ai_status, "queued")
                self.assertEqual(
                    set(ticket.ai_requested_artifacts.split(",")),
                    {"triage", "route"},
                )
            self.assertIsNone(db.get(TicketRecord, "too-old").ai_status)
            self.assertIsNone(
                db.get(TicketRecord, "old-imported-today").ai_status
            )
            self.assertIsNone(db.get(TicketRecord, "paused").ai_status)

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
                    {"enabled": True, "queued": 1},
                )

            active = db.get(TicketRecord, "old-active")
            self.assertEqual(active.ai_status, "queued")
            self.assertEqual(
                set(active.ai_requested_artifacts.split(",")),
                {"triage", "route"},
            )
            self.assertIsNone(db.get(TicketRecord, "old-closed").ai_status)

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
