import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import Base, SyncStateRecord, TicketRecord
from app.backend.integrations import sync
from app.backend.integrations.freshservice import FreshserviceRateLimited
from app.backend.schema import ExternalTicket


class _BatchedFreshserviceAdapter:
    provider_name = "freshservice"

    def __init__(self, recent, historical, *, remaining=500):
        self.recent = recent
        self.historical = historical
        self.remaining = remaining
        self.calls = []
        self.conversation_calls = []

    async def fetch_ticket_page(
        self,
        *,
        since,
        page,
        workspace_index,
        order_type,
        include_resources,
    ):
        if since == sync.BACKGROUND_HISTORY_EPOCH:
            lane = "background"
        elif since < datetime.utcnow() - timedelta(days=31):
            lane = "history"
        elif since < datetime.utcnow() - timedelta(days=29):
            lane = "repair"
        else:
            lane = "recent"
        self.calls.append((lane, page, order_type, include_resources))
        tickets = self.historical if lane in {"background", "history"} else (
            self.recent if lane == "recent" else []
        )
        return SimpleNamespace(
            tickets=tickets,
            has_next_page=lane in {"background", "history"},
            workspace_count=1,
        )

    async def fetch_ticket_conversations(self, external_id, max_pages=None):
        self.conversation_calls.append(external_id)
        return []

    def rate_limit_snapshot(self):
        return {"total": 500, "remaining": self.remaining, "used": 1}

    def should_pause_requests(self):
        return self.remaining <= 10


class _RateLimitedAdapter(_BatchedFreshserviceAdapter):
    async def fetch_ticket_page(self, **kwargs):
        self.calls.append(("attempt", kwargs["page"], kwargs["order_type"], False))
        raise FreshserviceRateLimited(75)


class _TimestampRepairAdapter(_BatchedFreshserviceAdapter):
    """Return old-cursor data only to the dedicated repair lane."""

    def __init__(self, repaired_ticket):
        super().__init__([], [], remaining=500)
        self.repaired_ticket = repaired_ticket
        self.lanes = []
        self.lane_since = []

    async def fetch_ticket_page(self, **kwargs):
        repair = kwargs["since"] < datetime.utcnow() - timedelta(days=27)
        lane = "repair" if repair else "recent"
        self.lanes.append((lane, kwargs["page"]))
        self.lane_since.append((lane, kwargs["since"]))
        if repair:
            # Let the repair page persist before the shared provider budget
            # stops any lower-priority background-history request.
            self.remaining = 0
            tickets = [self.repaired_ticket]
        else:
            self.remaining = 500
            tickets = []
        return SimpleNamespace(
            tickets=tickets,
            has_next_page=False,
            workspace_count=1,
        )


class _MixedHistoryAdapter(_BatchedFreshserviceAdapter):
    """Expose recent activity inside a multi-page historical inventory."""

    def __init__(self, pages):
        super().__init__([], [], remaining=500)
        self.pages = pages

    async def fetch_ticket_page(self, **kwargs):
        background = kwargs["since"] == sync.BACKGROUND_HISTORY_EPOCH
        lane = "background" if background else "recent"
        page = kwargs["page"]
        self.calls.append(
            (lane, page, kwargs["order_type"], kwargs["include_resources"])
        )
        tickets = self.pages[page - 1] if background else []
        return SimpleNamespace(
            tickets=tickets,
            has_next_page=background and page < len(self.pages),
            workspace_count=1,
        )


class FreshserviceBatchedSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.now = datetime.utcnow().replace(microsecond=0)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def _ticket(external_id, created_at, updated_at):
        return ExternalTicket(
            external_id=external_id,
            subject=f"Ticket {external_id}",
            description="Description",
            reporter="requester@example.com",
            priority="P3",
            status="Open",
            created_at=created_at,
            updated_at=updated_at,
        )

    def _run(self, adapter):
        env = {
            "FRESHSERVICE_RECENT_PAGES_PER_SYNC": "1",
            "FRESHSERVICE_HISTORY_PAGES_PER_SYNC": "1",
            "FRESHSERVICE_CONVERSATIONS_PER_SYNC": "1",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "refresh_ticket_documents_if_indexed"),
        ):
            return sync.sync_tickets_from_external(adapter)

    def test_automatic_sync_prioritizes_recent_then_downloads_one_background_page(self):
        recent = self._ticket("recent", self.now, self.now)
        historical = self._ticket(
            "historical",
            self.now - timedelta(days=500),
            self.now - timedelta(days=400),
        )
        adapter = _BatchedFreshserviceAdapter([recent], [historical])

        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["recent_pages"], 1)
        self.assertEqual(result["background_history_pages"], 1)
        self.assertEqual(result["history_pages"], 0)
        self.assertEqual(adapter.calls, [
            ("recent", 1, "asc", True),
            ("repair", 1, "asc", True),
            ("background", 1, "asc", True),
        ])
        with self.session_factory() as db:
            self.assertEqual(
                {row.external_id for row in db.query(TicketRecord).all()},
                {"recent", "historical"},
            )
            self.assertIsNone(
                db.query(TicketRecord).filter_by(
                    external_id="historical"
                ).one().ai_status
            )
            state = db.query(SyncStateRecord).one()
            self.assertIsNone(state.history_requested_at)
            self.assertEqual(state.background_history_page, 2)
            self.assertEqual(state.background_history_processed, 1)
            self.assertFalse(state.background_history_complete)

    def test_upgrade_replays_timestamp_stats_behind_incremental_cursor_once(self):
        resolved_at = self.now - timedelta(days=2)
        external_id = "closed-before-stats-include"
        repaired = ExternalTicket(
            external_id=external_id,
            subject="Historical closure",
            description="Provider content",
            reporter="requester@example.com",
            priority="P3",
            status="Closed",
            created_at=self.now - timedelta(days=10),
            updated_at=self.now - timedelta(days=1),
            resolved_at=resolved_at,
        )
        adapter = _TimestampRepairAdapter(repaired)
        with self.session_factory() as db:
            db.add(TicketRecord(
                id="ticket-needing-provider-timestamp",
                subject=repaired.subject,
                description=repaired.description,
                reporter=repaired.reporter,
                priority=repaired.priority,
                status="Closed",
                workflow_status="Closed",
                external_source="freshservice",
                binding_id="legacy",
                external_id=external_id,
                external_status="Closed",
                external_created_at=repaired.created_at,
                external_updated_at=repaired.updated_at,
                external_resolved_at=None,
                resolved_at=None,
            ))
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.now - timedelta(seconds=5),
                recent_completed_at=self.now - timedelta(seconds=5),
                provider_timestamp_repair_version=0,
            ))
            db.commit()

        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["recent_pages"], 1)
        self.assertEqual(result["provider_timestamp_repair_pages"], 1)
        self.assertEqual(adapter.lanes, [("recent", 1), ("repair", 1)])
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).filter_by(
                external_id=external_id
            ).one()
            self.assertEqual(ticket.external_resolved_at, resolved_at)
            self.assertEqual(ticket.resolved_at, resolved_at)
            state = db.query(SyncStateRecord).one()
            self.assertEqual(
                state.provider_timestamp_repair_version,
                sync.PROVIDER_TIMESTAMP_REPAIR_VERSION,
            )
            self.assertEqual(state.provider_timestamp_repair_processed, 1)
            self.assertIsNotNone(state.provider_timestamp_repair_completed_at)
            state.background_history_complete = True
            state.next_retry_at = None
            db.commit()

        adapter.remaining = 500
        adapter.lanes = []
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            state.next_retry_at = None
            db.commit()
        repeated = self._run(adapter)

        self.assertEqual(repeated["provider_timestamp_repair_pages"], 0)
        self.assertEqual(adapter.lanes, [("recent", 1)])

    def test_repair_version_upgrade_restarts_at_thirty_day_boundary_once(self):
        resolved_at = self.now - timedelta(days=29)
        external_id = "closure-inside-thirty-day-ops-window"
        repaired = ExternalTicket(
            external_id=external_id,
            subject="Operational-window closure",
            description="Provider content",
            reporter="requester@example.com",
            priority="P3",
            status="Closed",
            created_at=self.now - timedelta(days=30),
            updated_at=self.now - timedelta(days=29),
            resolved_at=resolved_at,
        )
        adapter = _TimestampRepairAdapter(repaired)
        with self.session_factory() as db:
            db.add(TicketRecord(
                id="ticket-needing-expanded-provider-repair",
                subject=repaired.subject,
                description=repaired.description,
                reporter=repaired.reporter,
                priority=repaired.priority,
                status="Closed",
                workflow_status="Closed",
                external_source="freshservice",
                binding_id="legacy",
                external_id=external_id,
                external_status="Closed",
                external_created_at=repaired.created_at,
                external_updated_at=repaired.updated_at,
                external_resolved_at=None,
                resolved_at=None,
            ))
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=self.now - timedelta(seconds=5),
                recent_completed_at=self.now - timedelta(seconds=5),
                provider_timestamp_repair_version=(
                    sync.PROVIDER_TIMESTAMP_REPAIR_VERSION - 1
                ),
                provider_timestamp_repair_started_at=self.now - timedelta(days=2),
                provider_timestamp_repair_completed_at=self.now - timedelta(days=1),
                provider_timestamp_repair_page=73,
                provider_timestamp_repair_processed=7_200,
            ))
            db.commit()

        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(adapter.lanes, [("recent", 1), ("repair", 1)])
        repair_since = dict(adapter.lane_since)["repair"]
        repair_age = datetime.utcnow() - repair_since
        self.assertGreaterEqual(
            repair_age,
            timedelta(days=sync.PROVIDER_TIMESTAMP_REPAIR_DAYS),
        )
        self.assertLess(repair_age, timedelta(days=31))
        with self.session_factory() as db:
            ticket = db.query(TicketRecord).filter_by(
                external_id=external_id
            ).one()
            self.assertEqual(ticket.external_resolved_at, resolved_at)
            state = db.query(SyncStateRecord).one()
            self.assertEqual(
                state.provider_timestamp_repair_version,
                sync.PROVIDER_TIMESTAMP_REPAIR_VERSION,
            )
            self.assertEqual(state.provider_timestamp_repair_processed, 1)
            self.assertEqual(state.provider_timestamp_repair_page, 1)
            state.background_history_complete = True
            state.next_retry_at = None
            db.commit()

        adapter.remaining = 500
        adapter.lanes = []
        repeated = self._run(adapter)
        self.assertEqual(repeated["provider_timestamp_repair_pages"], 0)
        self.assertEqual(adapter.lanes, [("recent", 1)])

    def test_history_upgrade_reopens_early_completion_and_exhausts_provider_pages(self):
        historical = self._ticket(
            "historical-after-false-boundary",
            self.now - timedelta(days=500),
            self.now - timedelta(days=400),
        )
        recently_updated = self._ticket(
            "recent-activity-inside-history-page",
            self.now - timedelta(days=600),
            self.now - timedelta(days=1),
        )
        final_historical = self._ticket(
            "final-historical-page",
            self.now - timedelta(days=700),
            self.now - timedelta(days=650),
        )
        adapter = _MixedHistoryAdapter([
            [historical, recently_updated],
            [final_historical],
        ])
        with self.session_factory() as db:
            recent_completed_at = self.now - timedelta(minutes=1)
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                last_synced_at=recent_completed_at - timedelta(seconds=5),
                recent_completed_at=recent_completed_at,
                provider_timestamp_repair_version=(
                    sync.PROVIDER_TIMESTAMP_REPAIR_VERSION
                ),
                background_history_page=17,
                background_history_complete=True,
                background_history_processed=1_700,
                background_history_started_at=self.now - timedelta(days=1),
                background_history_through_at=(
                    recent_completed_at - timedelta(days=sync.AUTOMATIC_FETCH_DAYS)
                ),
            ))
            db.commit()

        first = self._run(adapter)

        self.assertEqual(first["background_history_pages"], 1)
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(
                state.background_history_scan_version,
                sync.BACKGROUND_HISTORY_SCAN_VERSION,
            )
            self.assertEqual(state.background_history_page, 2)
            self.assertEqual(state.background_history_processed, 2)
            self.assertFalse(state.background_history_complete)
            self.assertEqual(
                {
                    row.external_id
                    for row in db.query(TicketRecord).all()
                },
                {historical.external_id},
            )

        second = self._run(adapter)

        self.assertEqual(second["background_history_pages"], 1)
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertTrue(state.background_history_complete)
            self.assertEqual(state.background_history_processed, 3)
            self.assertEqual(
                {
                    row.external_id
                    for row in db.query(TicketRecord).all()
                },
                {historical.external_id, final_historical.external_id},
            )

    def test_admin_requested_old_range_runs_after_recent_lane(self):
        recent = self._ticket("recent", self.now, self.now)
        historical = self._ticket(
            "historical",
            self.now - timedelta(days=500),
            self.now - timedelta(days=400),
        )
        adapter = _BatchedFreshserviceAdapter([recent], [historical])
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                history_since_at=self.now - timedelta(days=500),
                history_until_at=self.now - timedelta(days=300),
                history_requested_at=self.now,
                history_requested_by="admin",
                history_complete=False,
            ))
            db.commit()

        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["recent_pages"], 1)
        self.assertEqual(result["background_history_pages"], 1)
        self.assertEqual(result["history_pages"], 1)
        self.assertEqual(adapter.calls, [
            ("recent", 1, "asc", True),
            ("repair", 1, "asc", True),
            ("background", 1, "asc", True),
            ("history", 1, "asc", True),
        ])
        self.assertEqual(adapter.conversation_calls, ["recent"])
        with self.session_factory() as db:
            self.assertEqual(
                {row.external_id for row in db.query(TicketRecord).all()},
                {"recent", "historical"},
            )
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.last_status, "success")
            self.assertEqual(state.history_page, 2)
            self.assertFalse(state.history_complete)
            self.assertEqual(state.history_processed, 1)
            self.assertEqual(state.background_history_page, 2)
            self.assertEqual(state.background_history_processed, 1)
            self.assertEqual(state.conversations_processed, 1)
            self.assertIsNotNone(state.last_synced_at)
            self.assertIsNone(state.run_token)

    def test_retry_after_is_persisted_as_a_clean_throttle_not_an_error(self):
        adapter = _RateLimitedAdapter([], [])

        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["throttled"], 1)
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.last_status, "throttled")
            self.assertIsNone(state.last_error)
            self.assertGreater(
                state.next_retry_at,
                datetime.utcnow() + timedelta(seconds=60),
            )
            self.assertIsNone(state.run_token)

    def test_live_lease_defers_overlapping_manual_or_scheduled_run(self):
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                run_token="active-run",
                run_started_at=datetime.utcnow(),
                last_status="running",
            ))
            db.commit()
        adapter = _BatchedFreshserviceAdapter([], [])

        result = self._run(adapter)

        self.assertEqual(result["deferred"], 1)
        self.assertEqual(adapter.calls, [])

    def test_manual_recent_cursor_does_not_reset_a_live_scheduler_lease(self):
        claimed_at = datetime.utcnow()
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                run_token="scheduler-owner",
                run_started_at=claimed_at,
                recent_since_at=claimed_at - timedelta(days=3),
                recent_cycle_started_at=claimed_at,
                recent_page=9,
                recent_workspace_index=2,
                last_status="running",
            ))
            db.commit()

        adapter = _BatchedFreshserviceAdapter([], [])
        with self.session_factory() as db:
            self.assertFalse(sync._queue_freshservice_manual_recent_sync(
                db, adapter, "legacy", days=14, now=claimed_at
            ))

        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.run_token, "scheduler-owner")
            self.assertEqual(state.recent_page, 9)
            self.assertEqual(state.recent_workspace_index, 2)
            self.assertEqual(state.last_status, "running")

    def test_manual_freshservice_entrypoint_preserves_live_scheduler_cursor(self):
        claimed_at = datetime.utcnow()
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                run_token="scheduler-owner",
                run_started_at=claimed_at,
                recent_since_at=claimed_at - timedelta(days=3),
                recent_cycle_started_at=claimed_at,
                recent_page=11,
                recent_workspace_index=1,
                last_status="running",
            ))
            db.commit()
        adapter = _BatchedFreshserviceAdapter([], [])
        batch = {
            "new": 0, "updated": 0, "errors": 0, "fetched": 0,
            "deferred": 1, "recent_pages": 0,
        }
        with (
            patch.object(sync, "SessionLocal", self.session_factory),
            patch.object(sync, "sync_tickets_from_external", return_value=batch),
        ):
            result = sync.fetch_tickets_by_days(adapter, days=14)
        self.assertTrue(result["queued"])
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.run_token, "scheduler-owner")
            self.assertEqual(state.recent_page, 11)
            self.assertEqual(state.recent_workspace_index, 1)

    def test_manual_cursor_conditional_update_refuses_a_claim_that_wins_the_race(self):
        """A winner between inspection and mutation cannot be overwritten."""
        state = MagicMock(
            id=17,
            run_token=None,
            run_started_at=None,
        )
        locked = MagicMock()
        locked.one_or_none.return_value = state
        lookup = MagicMock()
        lookup.filter.return_value.with_for_update.return_value = locked
        mutation = MagicMock()
        mutation.filter.return_value.update.return_value = 0
        db = MagicMock()
        db.query.side_effect = [lookup, mutation]
        adapter = _BatchedFreshserviceAdapter([], [])

        self.assertFalse(sync._queue_freshservice_manual_recent_sync(
            db, adapter, "legacy", days=14, now=datetime(2026, 1, 1)
        ))
        locked.one_or_none.assert_called_once_with()
        mutation.filter.assert_called_once()
        mutation.filter.return_value.update.assert_called_once()
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()

    def test_page_persistence_renews_claim_before_committing_cursor(self):
        checkpoints = []
        original = sync._require_freshservice_run_owner

        def tracked_checkpoint(db, state, token, *, renew, lease_seconds):
            checkpoints.append(renew)
            return original(
                db,
                state,
                token,
                renew=renew,
                lease_seconds=lease_seconds,
            )

        adapter = _BatchedFreshserviceAdapter(
            [self._ticket("recent", self.now, self.now)],
            [],
            remaining=0,
        )
        with patch.object(
            sync,
            "_require_freshservice_run_owner",
            side_effect=tracked_checkpoint,
        ):
            result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(checkpoints[:3], [True, False, True])

    def test_lost_claim_during_page_persistence_rolls_back_ticket(self):
        calls = 0
        original = sync._require_freshservice_run_owner

        def lose_claim_before_publish(
            db, state, token, *, renew, lease_seconds
        ):
            nonlocal calls
            calls += 1
            if calls == 3:
                # A replacement owner becomes durable after the provider
                # fetch but before this worker is allowed to publish rows.
                db.rollback()
                db.query(SyncStateRecord).filter(
                    SyncStateRecord.id == state.id,
                ).update({
                    SyncStateRecord.run_token: "replacement-during-page",
                    SyncStateRecord.run_started_at: datetime.utcnow(),
                    SyncStateRecord.last_status: "running",
                }, synchronize_session=False)
                db.commit()
                raise sync._FreshserviceRunClaimLost("claim replaced")
            return original(
                db,
                state,
                token,
                renew=renew,
                lease_seconds=lease_seconds,
            )

        adapter = _BatchedFreshserviceAdapter(
            [self._ticket("must-not-publish", self.now, self.now)],
            [],
            remaining=0,
        )
        with patch.object(
            sync,
            "_require_freshservice_run_owner",
            side_effect=lose_claim_before_publish,
        ):
            result = self._run(adapter)

        self.assertEqual(result["deferred"], 1)
        with self.session_factory() as db:
            self.assertEqual(db.query(TicketRecord).count(), 0)
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.run_token, "replacement-during-page")
            self.assertEqual(state.last_status, "running")

    def test_expired_owner_cannot_clear_a_replacement_sync_claim(self):
        session_factory = self.session_factory

        class ClaimReplacingAdapter(_BatchedFreshserviceAdapter):
            async def fetch_ticket_page(self, **kwargs):
                with session_factory() as other_db:
                    state = other_db.query(SyncStateRecord).one()
                    state.run_token = "replacement-run"
                    state.run_started_at = datetime.utcnow()
                    state.last_status = "running"
                    other_db.commit()
                return await super().fetch_ticket_page(**kwargs)

        adapter = ClaimReplacingAdapter([], [])
        result = self._run(adapter)

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["deferred"], 1)
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.run_token, "replacement-run")
            self.assertEqual(state.last_status, "running")

    def test_expired_unreplaced_owner_cannot_verify_or_renew_its_lease(self):
        """A paused replica must yield at expiry before a successor claims."""
        lease_seconds = 120
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                run_token="expired-owner",
                run_started_at=datetime.utcnow() - timedelta(
                    seconds=lease_seconds + 1
                ),
                last_status="running",
            ))
            db.commit()

            state = db.query(SyncStateRecord).one()
            for renew in (False, True):
                with self.assertRaises(sync._FreshserviceRunClaimLost):
                    sync._require_freshservice_run_owner(
                        db,
                        state,
                        "expired-owner",
                        renew=renew,
                        lease_seconds=lease_seconds,
                    )
                db.rollback()

            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.run_token, "expired-owner")
            self.assertLess(
                state.run_started_at,
                datetime.utcnow() - timedelta(seconds=lease_seconds),
            )

    def test_expired_unreplaced_owner_cannot_publish_fetched_page(self):
        """Expiry during remote I/O fences the old owner before its DB write."""
        session_factory = self.session_factory

        class LeaseExpiringAdapter(_BatchedFreshserviceAdapter):
            async def fetch_ticket_page(self, **kwargs):
                with session_factory() as other_db:
                    state = other_db.query(SyncStateRecord).one()
                    state.run_started_at = datetime.utcnow() - timedelta(
                        seconds=901
                    )
                    other_db.commit()
                return await super().fetch_ticket_page(**kwargs)

        result = self._run(LeaseExpiringAdapter(
            [self._ticket("must-not-publish-after-expiry", self.now, self.now)],
            [],
        ))

        self.assertEqual(result["deferred"], 1)
        with self.session_factory() as db:
            self.assertEqual(db.query(TicketRecord).count(), 0)
            state = db.query(SyncStateRecord).one()
            self.assertIsNotNone(state.run_token)
            self.assertLess(
                state.run_started_at,
                datetime.utcnow() - timedelta(seconds=900),
            )

    def test_hydration_refresh_cannot_publish_throttle_for_replacement_owner(self):
        """A long derived refresh cannot commit its throttle state after expiry."""
        with self.session_factory() as db:
            db.add(SyncStateRecord(
                binding_id="legacy",
                provider="freshservice",
                run_token="hydration-owner",
                run_started_at=datetime.utcnow(),
                last_status="running",
            ))
            db.add(TicketRecord(
                id="hydration-ticket",
                subject="Hydration",
                description="old provider description",
                reporter="requester@example.com",
                priority="P3",
                status="Open",
                external_source="freshservice",
                binding_id="legacy",
                external_id="hydration-external",
                external_updated_at=self.now,
                external_created_at=self.now,
            ))
            db.commit()

            state = db.query(SyncStateRecord).one()
            adapter = _BatchedFreshserviceAdapter([], [], remaining=0)

            async def fetch_ticket_details(_external_id):
                return self._ticket(
                    "hydration-external", self.now, self.now
                ).model_copy(update={
                    "description": "new provider description",
                })

            adapter.fetch_ticket_details = fetch_ticket_details

            def checkpoint(renew):
                return sync._require_freshservice_run_owner(
                    db,
                    state,
                    "hydration-owner",
                    renew=renew,
                    lease_seconds=120,
                )

            def replace_owner(_db, _ticket):
                with self.session_factory() as replacement_db:
                    replacement = replacement_db.query(SyncStateRecord).one()
                    replacement.run_token = "replacement-after-refresh"
                    replacement.run_started_at = datetime.utcnow()
                    replacement.last_status = "running"
                    replacement.next_retry_at = None
                    replacement_db.commit()
                return 0

            with patch.object(
                sync, "refresh_ticket_documents_if_indexed", side_effect=replace_owner
            ):
                with self.assertRaises(sync._FreshserviceRunClaimLost):
                    sync._hydrate_freshservice_conversations(
                        db,
                        state=state,
                        adapter=adapter,
                        binding_id="legacy",
                        limit=1,
                        claim_checkpoint=checkpoint,
                    )

        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.run_token, "replacement-after-refresh")
            self.assertEqual(state.last_status, "running")
            self.assertIsNone(state.next_retry_at)

    def test_rate_limit_handler_cannot_overwrite_a_replacement_sync_claim(self):
        session_factory = self.session_factory

        class RateLimitedClaimReplacingAdapter(_BatchedFreshserviceAdapter):
            async def fetch_ticket_page(self, **_kwargs):
                with session_factory() as other_db:
                    state = other_db.query(SyncStateRecord).one()
                    state.run_token = "replacement-rate-limit-run"
                    state.run_started_at = datetime.utcnow()
                    state.last_status = "running"
                    other_db.commit()
                raise FreshserviceRateLimited(75)

        result = self._run(RateLimitedClaimReplacingAdapter([], []))

        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(result["throttled"], 0)
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.run_token, "replacement-rate-limit-run")
            self.assertEqual(state.last_status, "running")
            self.assertIsNone(state.next_retry_at)

    def test_old_ticket_range_requires_explicit_queue_and_cannot_be_replaced(self):
        adapter = _BatchedFreshserviceAdapter([], [])
        start_at = self.now - timedelta(days=90)
        end_at = self.now - timedelta(days=30)
        with patch.object(sync, "SessionLocal", self.session_factory):
            result = sync.queue_old_ticket_fetch(
                adapter,
                start_at=start_at,
                end_at=end_at,
                requested_by="admin",
            )
            with self.assertRaisesRegex(ValueError, "already_queued"):
                sync.queue_old_ticket_fetch(
                    adapter,
                    start_at=start_at,
                    end_at=end_at,
                    requested_by="admin",
                )

        self.assertTrue(result["queued"])
        with self.session_factory() as db:
            state = db.query(SyncStateRecord).one()
            self.assertEqual(state.history_since_at, start_at)
            self.assertEqual(state.history_until_at, end_at)
            self.assertFalse(state.history_complete)
            self.assertEqual(state.history_requested_by, "admin")


if __name__ == "__main__":
    unittest.main()
