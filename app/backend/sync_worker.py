import os
import asyncio
import threading
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from .database import SessionLocal, SyncStateRecord, TicketRecord
from .integrations.sync import sync_tickets_from_external
from .integrations.registry import get_adapter
from . import settings as settings_module

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()

_PROCESS_ROLE_ENV = "TICKETY_PROCESS_ROLE"
_SCHEDULER_ENABLED_ENV = "TICKETY_SCHEDULER_ENABLED"
_VALID_PROCESS_ROLES = {"api", "worker", "all"}


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
    the gaps — triage first, then summary, then resolution. Processes up
    to 10 tickets per 30‑second sweep."""
    try:
        db = SessionLocal()
        auto_triage = settings_module.automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE")
        auto_summary = settings_module.automation_enabled("AUTO_SUMMARIZE_ENABLED")
        auto_resolution = settings_module.automation_enabled("AUTO_RESOLVE_ENABLED")
        # Find tickets missing ANY AI data (prioritize untriaged first)
        untriaged = (
            db.query(TicketRecord).filter(TicketRecord.ai_reasoning.is_(None)).limit(5).all()
            if auto_triage else []
        )
        no_summary = (
            db.query(TicketRecord).filter(
                TicketRecord.ai_reasoning.isnot(None),
                TicketRecord.summary.is_(None)
            ).limit(5).all()
            if auto_summary else []
        )
        no_resolution = (
            db.query(TicketRecord).filter(
                TicketRecord.ai_reasoning.isnot(None),
                TicketRecord.summary.isnot(None),
                TicketRecord.recommended_solution.is_(None)
            ).limit(5).all()
            if auto_resolution else []
        )

        if untriaged or no_summary or no_resolution:
            print(f"[auto-triage] gaps: {len(untriaged)} untriaged, {len(no_summary)} no-summary, {len(no_resolution)} no-plan")

        if untriaged:
            import asyncio
            from .main import _auto_process
            for t in untriaged:
                try:
                    t2 = db.query(TicketRecord).filter(TicketRecord.id == t.id).first()
                    if t2:
                        asyncio.run(_auto_process(t2, db))
                except Exception as e:
                    print(f"[auto-triage] error: {e}")
                    db.rollback()

        # Fill missing summaries
        if no_summary:
            import asyncio
            from .brain import IntelligenceEngine
            from .llm_manager import LLMManager
            from . import intelligence as intel
            eng = IntelligenceEngine(LLMManager())
            for t in no_summary:
                try:
                    t2 = db.query(TicketRecord).filter(TicketRecord.id == t.id).first()
                    if t2:
                        s = asyncio.run(intel.summarize_ticket(eng.llm, t2))
                        if s:
                            t2.summary = s
                            db.commit()
                            print(f"[auto-triage] summary filled for {t2.id[:8]}")
                except Exception as e:
                    print(f"[auto-triage] summary error: {e}")
                    db.rollback()

        # Fill missing resolution plans
        if no_resolution:
            import asyncio, json
            from .brain import IntelligenceEngine
            from .llm_manager import LLMManager
            from . import intelligence as intel
            eng = IntelligenceEngine(LLMManager())
            for t in no_resolution:
                try:
                    t2 = db.query(TicketRecord).filter(TicketRecord.id == t.id).first()
                    if t2:
                        plan = asyncio.run(intel.recommend_resolution(eng.llm, t2))
                        t2.recommended_solution = json.dumps(plan)
                        db.commit()
                        print(f"[auto-triage] resolution filled for {t2.id[:8]}")
                except Exception as e:
                    print(f"[auto-triage] resolution error: {e}")
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
                    print(f"[auto-triage] risk error: {e}")
                    db.rollback()

        db.close()
    except Exception as e:
        print(f"[auto-triage] job error: {e}")


def _sync_job():
    provider = os.getenv("ITSM_PROVIDER", "standalone")
    if provider == "external":
        provider = "freshservice"
    if provider in ("standalone", "none", ""):
        return  # No external sync in standalone mode
    try:
        adapter = get_adapter()
        result = sync_tickets_from_external(adapter)
        print(f"[sync_worker] {adapter.provider_name}: {result}")
    except Exception as e:
        print(f"[sync_worker] error: {e}")


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
        # Always reflect the CURRENTLY configured provider from env, not the
        # stale DB record that may still hold the previous provider's name.
        current_provider = os.getenv("ITSM_PROVIDER", "standalone")
        if current_provider == "external":
            current_provider = "freshservice"
        state = db.query(SyncStateRecord).filter(
            SyncStateRecord.provider == current_provider
        ).first()
        if not state:
            return {"provider": current_provider, "last_synced_at": None, "last_synced": 0,
                    "last_status": "idle", "last_error": None, "total_synced": 0}
        return {
            "provider": current_provider,
            "last_synced_at": state.last_synced_at.isoformat() if state.last_synced_at else None,
            "last_status": state.last_status,
            "last_error": state.last_error,
            "total_synced": state.total_synced,
        }
    finally:
        db.close()
