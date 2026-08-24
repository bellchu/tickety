import os
import asyncio
import threading
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import or_

from .database import SessionLocal, SyncStateRecord, TicketRecord
from .integrations.sync import (
    AUTOMATIC_AI_LOOKBACK_DAYS,
    freshservice_sync_limits,
    queue_recent_automatic_ai,
    sync_tickets_from_external,
)
from .integrations.registry import configured_provider, get_adapter
from .integrations.bindings import expire_due_bindings, get_active_binding
from . import settings as settings_module

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()

_PROCESS_ROLE_ENV = "TICKETY_PROCESS_ROLE"
_SCHEDULER_ENABLED_ENV = "TICKETY_SCHEDULER_ENABLED"
_VALID_PROCESS_ROLES = {"api", "worker", "all"}


def _refresh_admin_settings() -> None:
    """Pick up portal-approved settings without restarting the worker pod."""
    try:
        settings_module.refresh_settings_from_db()
    except Exception as exc:
        print(f"[settings] worker refresh error kind={type(exc).__name__}")


def process_role() -> str:
    """Return this process's explicit runtime role.

    Production defaults to an API-only process so adding API replicas can
    never multiply scheduled jobs. Demo mode retains the historical combined
    API + scheduler process unless a role is explicitly configured.
    """
    configured = os.getenv(_PROCESS_ROLE_ENV, "").strip().lower()
    if configured:
        if configured not in _VALID_PROCESS_ROLES:
            raise ValueError(
                f"{_PROCESS_ROLE_ENV} must be one of: "
                f"{', '.join(sorted(_VALID_PROCESS_ROLES))}"
            )
        return configured
    return "all" if settings_module.is_demo_mode() else "api"


def scheduler_enabled_for_process() -> bool:
    """Whether this process may own scheduled jobs.

    The optional enable flag is a kill switch, not a way to turn an API role
    into a worker. This keeps a mistaken boolean on replicated API pods from
    reintroducing duplicate schedulers.
    """
    role = process_role()
    configured = os.getenv(_SCHEDULER_ENABLED_ENV)
    if configured is not None:
        normalized = configured.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized not in {"1", "true", "yes", "on"}:
            raise ValueError(
                f"{_SCHEDULER_ENABLED_ENV} must be a boolean value"
            )
    return role in {"worker", "all"}


def _bounded_interval(env_name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        configured = default
    return max(minimum, min(configured, maximum))


def _auto_triage_job():
    """Background scanner: pick up tickets with missing AI data and fill
    the gaps — triage first, then summary, then resolution. The number of
    tickets admitted per sweep is bounded independently from provider RPM/TPM
    enforcement so a seven-day repair window cannot become a traffic burst."""
    _refresh_admin_settings()
    try:
        db = SessionLocal()
        batch_size = _bounded_interval(
            "AI_BACKGROUND_TICKETS_PER_SWEEP", 5, 1, 25
        )
        auto_triage = settings_module.automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE")
        auto_summary = settings_module.automation_enabled("AUTO_SUMMARIZE_ENABLED")
        auto_resolution = settings_module.automation_enabled("AUTO_RESOLVE_ENABLED")
        try:
            recent = queue_recent_automatic_ai(db, batch_size=batch_size)
        except Exception as exc:
            db.rollback()
            recent = {
                "lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
                "queued": 0,
            }
            print(
                "[auto-triage] recent lookback unavailable "
                f"kind={type(exc).__name__}"
            )
        # Only Tickety-owned records are eligible for the generic gap scan.
        # External tickets reach the queue only through the audited binding
        # switch plus realtime/seven-day eligibility; Portal tickets still
        # require an explicit authenticated request. The queued query remains
        # source-agnostic so authorized requests and expired claims progress.
        internal_automatic_source = or_(
            TicketRecord.external_source.is_(None),
            TicketRecord.external_source.in_(["manual", "standalone"]),
        )
        queued = db.query(TicketRecord).filter(
            or_(
                TicketRecord.ai_status == "queued",
                (
                    (TicketRecord.ai_status == "running")
                    & (TicketRecord.ai_lease_expires_at < datetime.utcnow())
                ),
            ),
            or_(
                TicketRecord.ai_next_attempt_at.is_(None),
                TicketRecord.ai_next_attempt_at <= datetime.utcnow(),
            ),
        ).limit(batch_size).all()
        remaining = max(0, batch_size - len(queued))
        # Find tickets missing ANY AI data (prioritize untriaged first)
        untriaged = (
            db.query(TicketRecord).filter(
                internal_automatic_source,
                TicketRecord.ai_reasoning.is_(None),
                or_(
                    TicketRecord.ai_status.is_(None),
                    TicketRecord.ai_status.notin_(["dead_letter", "failed"]),
                ),
            ).limit(remaining).all()
            if auto_triage and remaining else []
        )
        triage_candidates = list(
            {ticket.id: ticket for ticket in [*queued, *untriaged]}.values()
        )
        selected_ids = {ticket.id for ticket in triage_candidates}
        remaining = max(0, batch_size - len(selected_ids))

        summary_query = db.query(TicketRecord).filter(
            internal_automatic_source,
            TicketRecord.ai_reasoning.isnot(None),
            TicketRecord.summary.is_(None),
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_(
                    ["dead_letter", "failed", "running", "queued"]
                ),
            ),
            or_(
                TicketRecord.ai_next_attempt_at.is_(None),
                TicketRecord.ai_next_attempt_at <= datetime.utcnow(),
            ),
        )
        if selected_ids:
            summary_query = summary_query.filter(TicketRecord.id.notin_(selected_ids))
        no_summary = (
            summary_query.limit(remaining).all()
            if auto_summary and remaining else []
        )
        selected_ids.update(ticket.id for ticket in no_summary)
        remaining = max(0, batch_size - len(selected_ids))

        resolution_query = db.query(TicketRecord).filter(
            internal_automatic_source,
            TicketRecord.ai_reasoning.isnot(None),
            TicketRecord.summary.isnot(None),
            TicketRecord.recommended_solution.is_(None),
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_(
                    ["dead_letter", "failed", "running", "queued"]
                ),
            ),
            or_(
                TicketRecord.ai_next_attempt_at.is_(None),
                TicketRecord.ai_next_attempt_at <= datetime.utcnow(),
            ),
        )
        if selected_ids:
            resolution_query = resolution_query.filter(
                TicketRecord.id.notin_(selected_ids)
            )
        no_resolution = (
            resolution_query.limit(remaining).all()
            if auto_resolution and remaining else []
        )

        if recent["queued"] or queued or untriaged or no_summary or no_resolution:
            print(
                f"[auto-triage] recent={recent['queued']}, {len(queued)} queued, "
                f"{len(untriaged)} untriaged, "
                f"{len(no_summary)} no-summary, {len(no_resolution)} no-plan"
            )

        if triage_candidates:
            import asyncio
            from .main import _auto_process
            for t in triage_candidates:
                try:
                    t2 = db.query(TicketRecord).filter(
                        TicketRecord.id == t.id
                    ).with_for_update().first()
                    live_claim = bool(
                        t2
                        and t2.ai_status == "running"
                        and t2.ai_lease_expires_at
                        and t2.ai_lease_expires_at >= datetime.utcnow()
                    )
                    if t2 and not live_claim and t2.ai_status not in {"dead_letter", "failed"}:
                        db.commit()
                        asyncio.run(
                            _auto_process(
                                t2,
                                db,
                                force=t2.ai_status in {"queued", "running"},
                            )
                        )
                except Exception as e:
                    print(f"[auto-triage] error kind={type(e).__name__}")
                    db.rollback()

        # Fill missing summaries
        if no_summary:
            import asyncio
            from .main import _auto_process
            for t in no_summary:
                try:
                    t2 = db.query(TicketRecord).filter(
                        TicketRecord.id == t.id
                    ).with_for_update().first()
                    live_claim = bool(
                        t2
                        and t2.ai_status == "running"
                        and t2.ai_lease_expires_at
                        and t2.ai_lease_expires_at >= datetime.utcnow()
                    )
                    retry_due = bool(
                        t2
                        and (
                            t2.ai_next_attempt_at is None
                            or t2.ai_next_attempt_at <= datetime.utcnow()
                        )
                    )
                    if (
                        t2
                        and t2.summary is None
                        and not live_claim
                        and retry_due
                        and t2.ai_status not in {"queued", "dead_letter", "failed"}
                    ):
                        t2.ai_requested_artifacts = "summary"
                        t2.ai_status = "queued"
                        db.commit()
                        asyncio.run(_auto_process(t2, db, force=True))
                        print(f"[auto-triage] summary filled for {t2.id[:8]}")
                except Exception as e:
                    print(f"[auto-triage] summary error kind={type(e).__name__}")
                    db.rollback()

        # Fill missing resolution plans
        if no_resolution:
            import asyncio
            from .main import _auto_process
            for t in no_resolution:
                try:
                    t2 = db.query(TicketRecord).filter(
                        TicketRecord.id == t.id
                    ).with_for_update().first()
                    live_claim = bool(
                        t2
                        and t2.ai_status == "running"
                        and t2.ai_lease_expires_at
                        and t2.ai_lease_expires_at >= datetime.utcnow()
                    )
                    retry_due = bool(
                        t2
                        and (
                            t2.ai_next_attempt_at is None
                            or t2.ai_next_attempt_at <= datetime.utcnow()
                        )
                    )
                    if (
                        t2
                        and t2.recommended_solution is None
                        and not live_claim
                        and retry_due
                        and t2.ai_status not in {"queued", "dead_letter", "failed"}
                    ):
                        t2.ai_requested_artifacts = "resolution"
                        t2.ai_status = "queued"
                        db.commit()
                        asyncio.run(_auto_process(t2, db, force=True))
                        print(f"[auto-triage] resolution filled for {t2.id[:8]}")
                except Exception as e:
                    print(f"[auto-triage] resolution error kind={type(e).__name__}")
                    db.rollback()

        # Fix missing escalation risk (column added later, may be NULL)
        no_risk = db.query(TicketRecord).filter(
            TicketRecord.ai_reasoning.isnot(None),
            TicketRecord.escalation_risk == 0
        ).all()
        if no_risk:
            from . import intelligence as intel
            for t in no_risk:
                try:
                    t2 = db.query(TicketRecord).filter(TicketRecord.id == t.id).first()
                    if t2:
                        t2.escalation_risk = intel.escalation_risk(t2)
                        db.commit()
                except Exception as e:
                    print(f"[auto-triage] risk error kind={type(e).__name__}")
                    db.rollback()

        db.close()
    except Exception as e:
        print(f"[auto-triage] job error kind={type(e).__name__}")


def _sync_job():
    _refresh_admin_settings()
    provider = configured_provider()
    if provider in ("standalone", "none", ""):
        # An activated binding is authoritative over the legacy provider env.
        db = SessionLocal()
        try:
            expire_due_bindings(db)
            binding = get_active_binding(db)
        finally:
            db.close()
        if binding is None:
            return  # No external sync in standalone mode
    else:
        db = SessionLocal()
        try:
            expire_due_bindings(db)
            binding = get_active_binding(db, provider)
        finally:
            db.close()
    try:
        adapter = get_adapter(binding=binding) if binding else get_adapter()
        result = sync_tickets_from_external(
            adapter,
            binding_id=binding.id if binding else "legacy",
        )
        print(f"[sync_worker] {adapter.provider_name}: {result}")
    except Exception as e:
        print(f"[sync_worker] error kind={type(e).__name__}")


def start_sync_worker() -> bool:
    """Start the process-local scheduler once when this role owns jobs."""
    global _scheduler
    if not scheduler_enabled_for_process():
        return False
    with _lock:
        if _scheduler is not None:
            return False
        sync_interval = _bounded_interval("SYNC_INTERVAL_SECONDS", 60, 10, 86_400)
        triage_interval = _bounded_interval("AUTO_TRIAGE_INTERVAL_SECONDS", 30, 10, 86_400)
        scheduler = BackgroundScheduler(daemon=True)
        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "replace_existing": True,
        }
        scheduler.add_job(
            _sync_job,
            "interval",
            seconds=sync_interval,
            id="sync_job",
            misfire_grace_time=sync_interval,
            next_run_time=datetime.now(),
            **job_defaults,
        )
        scheduler.add_job(
            _auto_triage_job,
            "interval",
            seconds=triage_interval,
            id="auto_triage_job",
            misfire_grace_time=triage_interval,
            next_run_time=datetime.now(),
            **job_defaults,
        )
        try:
            scheduler.start()
        except Exception:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
            raise
        _scheduler = scheduler
        print(
            f"[sync_worker] started role={process_role()}, "
            f"sync every {sync_interval}s, auto-triage every {triage_interval}s"
        )
        return True


def stop_sync_worker(wait: bool = True) -> bool:
    """Stop the process-local scheduler once and optionally drain jobs."""
    global _scheduler
    with _lock:
        if _scheduler is None:
            return False
        scheduler = _scheduler
        _scheduler = None
        scheduler.shutdown(wait=wait)
        return True


def get_sync_status() -> dict:
    db = SessionLocal()
    try:
        expire_due_bindings(db)
        active_binding = get_active_binding(db)
        current_provider = configured_provider()
        binding_id = "legacy"
        if active_binding:
            current_provider = active_binding.provider
            binding_id = active_binding.id
        state = db.query(SyncStateRecord).filter(
            SyncStateRecord.binding_id == binding_id,
            SyncStateRecord.provider == current_provider
        ).first()
        local_ticket_count = db.query(TicketRecord).filter(
            TicketRecord.binding_id == binding_id,
            TicketRecord.external_source == current_provider,
        ).count()
        limits = freshservice_sync_limits()
        operational = {
            "local_ticket_count": local_ticket_count,
            "sync_interval_seconds": _bounded_interval(
                "SYNC_INTERVAL_SECONDS", 60, 10, 86_400
            ),
            "recent_pages_per_sync": limits["recent_pages"],
            "history_pages_per_sync": limits["history_pages"],
            "conversations_per_sync": limits["conversations"],
        }
        if not state:
            return {"provider": current_provider, "binding_id": binding_id,
                    "last_synced_at": None, "last_synced": 0,
                    "automatic_ai_enabled": False,
                    "automatic_ai_generation": None,
                    "automatic_ai_cutover_at": None,
                    "automatic_ai_enabled_at": None,
                    "automatic_ai_paused_at": None,
                    "automatic_ai_lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
                    "last_status": "idle", "last_error": None, "total_synced": 0,
                    "recent_since_at": None, "recent_cycle_started_at": None,
                    "recent_page": 1, "recent_workspace_index": 0,
                    "recent_completed_at": None, "history_page": 1,
                    "history_workspace_index": 0, "history_complete": False,
                    "history_processed": 0, "conversations_processed": 0,
                    "run_started_at": None, "run_finished_at": None,
                    "next_retry_at": None, "rate_limit_total": None,
                    "rate_limit_remaining": None, "rate_limit_used": None,
                    "last_batch_new": 0, "last_batch_updated": 0,
                    "last_batch_errors": 0, **operational}
        return {
            "provider": current_provider,
            "binding_id": binding_id,
            "last_synced_at": state.last_synced_at.isoformat() if state.last_synced_at else None,
            "automatic_ai_enabled": state.automatic_ai_enabled,
            "automatic_ai_generation": state.automatic_ai_generation,
            "automatic_ai_cutover_at": (
                state.automatic_ai_cutover_at.isoformat()
                if state.automatic_ai_cutover_at else None
            ),
            "automatic_ai_enabled_at": (
                state.automatic_ai_enabled_at.isoformat()
                if state.automatic_ai_enabled_at else None
            ),
            "automatic_ai_paused_at": (
                state.automatic_ai_paused_at.isoformat()
                if state.automatic_ai_paused_at else None
            ),
            "automatic_ai_lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS,
            "last_status": state.last_status or "idle",
            "last_error": state.last_error,
            "total_synced": state.total_synced or 0,
            "recent_since_at": (
                state.recent_since_at.isoformat() if state.recent_since_at else None
            ),
            "recent_cycle_started_at": (
                state.recent_cycle_started_at.isoformat()
                if state.recent_cycle_started_at else None
            ),
            "recent_page": state.recent_page or 1,
            "recent_workspace_index": state.recent_workspace_index or 0,
            "recent_completed_at": (
                state.recent_completed_at.isoformat()
                if state.recent_completed_at else None
            ),
            "history_page": state.history_page or 1,
            "history_workspace_index": state.history_workspace_index or 0,
            "history_complete": bool(state.history_complete),
            "history_processed": state.history_processed or 0,
            "conversations_processed": state.conversations_processed or 0,
            "run_started_at": (
                state.run_started_at.isoformat() if state.run_started_at else None
            ),
            "run_finished_at": (
                state.run_finished_at.isoformat() if state.run_finished_at else None
            ),
            "next_retry_at": (
                state.next_retry_at.isoformat() if state.next_retry_at else None
            ),
            "rate_limit_total": state.rate_limit_total,
            "rate_limit_remaining": state.rate_limit_remaining,
            "rate_limit_used": state.rate_limit_used,
            "last_batch_new": state.last_batch_new or 0,
            "last_batch_updated": state.last_batch_updated or 0,
            "last_batch_errors": state.last_batch_errors or 0,
            **operational,
        }
    finally:
        db.close()
