import os
import asyncio
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from .database import SessionLocal, SyncStateRecord, TicketRecord
from .integrations.sync import sync_tickets_from_external
from .integrations.registry import get_adapter

_scheduler: BackgroundScheduler = None
_lock = threading.Lock()


def _auto_triage_job():
    """Background scanner: pick up tickets with missing AI data and fill
    the gaps — triage first, then summary, then resolution. Processes up
    to 10 tickets per 30‑second sweep."""
    try:
        db = SessionLocal()
        # Find tickets missing ANY AI data (prioritize untriaged first)
        untriaged = db.query(TicketRecord).filter(
            TicketRecord.ai_reasoning.is_(None)
        ).limit(5).all()
        no_summary = db.query(TicketRecord).filter(
            TicketRecord.ai_reasoning.isnot(None),
            TicketRecord.summary.is_(None)
        ).limit(5).all()
        no_resolution = db.query(TicketRecord).filter(
            TicketRecord.ai_reasoning.isnot(None),
            TicketRecord.summary.isnot(None),
            TicketRecord.recommended_solution.is_(None)
        ).limit(5).all()

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
    if provider in ("standalone", "none", ""):
        return  # No external sync in standalone mode
    try:
        adapter = get_adapter()
        result = sync_tickets_from_external(adapter)
        print(f"[sync_worker] {adapter.provider_name}: {result}")
    except Exception as e:
        print(f"[sync_worker] error: {e}")


def start_sync_worker():
    global _scheduler
    with _lock:
        if _scheduler is not None:
            return
        interval = int(os.getenv("SYNC_INTERVAL_SECONDS", "60"))
        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(_sync_job, "interval", seconds=interval, id="sync_job")
        _scheduler.add_job(_auto_triage_job, "interval", seconds=30, id="auto_triage_job")
        _scheduler.start()
        print(f"[sync_worker] started, sync every {interval}s, auto-triage every 30s")


def stop_sync_worker():
    global _scheduler
    with _lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None


def get_sync_status() -> dict:
    db = SessionLocal()
    try:
        # Always reflect the CURRENTLY configured provider from env, not the
        # stale DB record that may still hold the previous provider's name.
        current_provider = os.getenv("ITSM_PROVIDER", "standalone")
        state = db.query(SyncStateRecord).first()
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