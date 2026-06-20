import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from ..database import (
    SessionLocal, TicketRecord, UserMappingRecord, SyncStateRecord,
)
from ..schema import ExternalTicket, WebhookEvent
from .registry import get_adapter


def _upsert_ticket(db: Session, ext: ExternalTicket, provider: str, overwrite: bool = False) -> tuple[str, Optional[TicketRecord]]:
    """Upsert an external ticket. Returns (action, ticket) where action is
    one of "new" / "updated" / "skipped". When `overwrite` is False and the
    ticket already exists locally, it is left untouched and ("skipped", None)
    is returned so callers can avoid re-fetching already-imported tickets."""
    existing = db.query(TicketRecord).filter(
        TicketRecord.external_source == provider,
        TicketRecord.external_id == ext.external_id,
    ).first()

    if existing and not overwrite:
        return "skipped", None

    if existing:
        changed = (
            existing.subject != ext.subject
            or existing.description != ext.description
            or existing.reporter != ext.reporter
            or existing.priority != ext.priority
            or existing.external_status != ext.status
            or existing.external_assignee_id != ext.assignee_id
            or existing.external_updated_at != ext.updated_at
            or (ext.url and existing.external_url != ext.url)
        )
        if not changed:
            # Nothing to write — count as skipped so the worker doesn't
            # report spurious "updated" activity on every poll.
            return "skipped", existing
        existing.subject = ext.subject
        existing.description = ext.description
        existing.reporter = ext.reporter
        existing.priority = ext.priority
        existing.external_status = ext.status
        existing.external_assignee_id = ext.assignee_id
        existing.external_updated_at = ext.updated_at
        existing.external_url = ext.url or existing.external_url
        existing.updated_at = datetime.utcnow()
        if ext.status.lower() in ("closed", "resolved"):
            existing.status = "Closed"
        else:
            existing.status = ext.status
        db.commit()
        db.refresh(existing)
        return "updated", existing

    new_ticket = TicketRecord(
        id=str(uuid.uuid4()),
        subject=ext.subject,
        description=ext.description,
        reporter=ext.reporter,
        status=ext.status,
        priority=ext.priority,
        external_source=provider,
        external_id=ext.external_id,
        external_url=ext.url,
        external_status=ext.status,
        external_assignee_id=ext.assignee_id,
        external_updated_at=ext.updated_at,
    )
    db.add(new_ticket)
    db.commit()
    db.refresh(new_ticket)
    return "new", new_ticket


def _existing_external_ids(db: Session, provider: str) -> set:
    """Return the set of external_ids already imported for `provider`.
    Used to pre-filter so we don't issue a DB query per fetched ticket."""
    rows = db.query(TicketRecord.external_id).filter(
        TicketRecord.external_source == provider,
        TicketRecord.external_id.isnot(None),
    ).all()
    return {r[0] for r in rows}


def sync_tickets_from_external(adapter=None) -> dict:
    adapter = adapter or get_adapter()
    db: Session = SessionLocal()
    result = {"new": 0, "updated": 0, "errors": 0}
    try:
        sync_state = db.query(SyncStateRecord).filter(
            SyncStateRecord.provider == adapter.provider_name
        ).first()
        if not sync_state:
            sync_state = SyncStateRecord(provider=adapter.provider_name, last_status="running")
            db.add(sync_state)
            db.commit()
            db.refresh(sync_state)

        since = sync_state.last_synced_at
        sync_state.last_status = "running"
        sync_state.last_error = None
        db.commit()

        import asyncio
        # run in a fresh event loop — this runs inside an APScheduler
        # ThreadPoolExecutor thread which has no running loop, so
        # asyncio.get_event_loop() raises "There is no current event loop
        # in thread". asyncio.run() creates/closes a loop per call.
        tickets: List[ExternalTicket] = asyncio.run(
            adapter.fetch_new_tickets(since=since)
        )

        for ext in tickets:
            try:
                action, ticket = _upsert_ticket(db, ext, adapter.provider_name, overwrite=True)
                if action == "new":
                    result["new"] += 1
                elif action == "updated":
                    result["updated"] += 1
            except Exception as e:
                print(f"[sync] error upserting ticket {ext.external_id}: {e}")
                result["errors"] += 1

        sync_state.last_synced_at = datetime.utcnow()
        sync_state.last_status = "success"
        sync_state.total_synced += len(tickets)
        db.commit()

    except Exception as e:
        sync_state = db.query(SyncStateRecord).filter(
            SyncStateRecord.provider == adapter.provider_name
        ).first()
        if sync_state:
            sync_state.last_status = "error"
            sync_state.last_error = str(e)
            db.commit()
        result["errors"] += 1
        print(f"[sync] fatal error: {e}")
    finally:
        db.close()

    return result


def fetch_tickets_by_days(adapter=None, days: int = 7, overwrite: bool = False) -> dict:
    """Manually fetch all tickets updated in the last `days` days from the
    external ITSM provider, walking every page while respecting rate limits.

    Skip-vs-overwrite: by default tickets already imported (matched by
    external_source + external_id) are *not* re-written, so re-running a fetch
    for an overlapping window won't clobber local AI triage / status changes.
    Pass overwrite=True to force-refresh existing records from the source.
    """
    days = max(1, min(int(days), 365))
    adapter = adapter or get_adapter()
    db: Session = SessionLocal()
    result = {
        "new": 0, "updated": 0, "skipped": 0, "errors": 0,
        "fetched": 0, "days": days, "overwrite": overwrite,
    }
    try:
        since = datetime.utcnow() - timedelta(days=days)

        import asyncio
        tickets: List[ExternalTicket] = asyncio.run(adapter.fetch_tickets_since(since))
        result["fetched"] = len(tickets)

        # Pre-load existing external ids once to avoid N queries.
        existing_ids = _existing_external_ids(db, adapter.provider_name)

        import os as _os
        auto_triage = _os.getenv("AUTO_TRIAGE", "").lower() == "true"
        new_tickets: list = []  # collect for auto-triage

        for ext in tickets:
            try:
                if ext.external_id in existing_ids and not overwrite:
                    result["skipped"] += 1
                    continue
                action, ticket = _upsert_ticket(db, ext, adapter.provider_name, overwrite=overwrite)
                if action == "new":
                    existing_ids.add(ext.external_id)
                    result["new"] += 1
                    if auto_triage and ticket:
                        new_tickets.append(ticket)
                elif action == "updated":
                    result["updated"] += 1
                elif action == "skipped":
                    result["skipped"] += 1
            except Exception as e:
                print(f"[fetch] error upserting ticket {ext.external_id}: {e}")
                result["errors"] += 1

        # Record a successful manual fetch on the sync state so the worker's
        # incremental cursor advances past what we just pulled in.
        sync_state = db.query(SyncStateRecord).filter(
            SyncStateRecord.provider == adapter.provider_name
        ).first()
        if not sync_state:
            sync_state = SyncStateRecord(provider=adapter.provider_name)
            db.add(sync_state)
        # Only advance the cursor when the manual fetch window starts at or
        # before the current cursor — i.e. it covers the gap the worker would
        # otherwise pick up. If the window starts *after* the cursor there's an
        # uncovered gap in between, so we must not advance (the worker will fill it).
        if not sync_state.last_synced_at or since <= sync_state.last_synced_at:
            sync_state.last_synced_at = datetime.utcnow()
        sync_state.last_status = "success"
        sync_state.last_error = None
        sync_state.total_synced += len(tickets)
        db.commit()

        # Auto-triage newly imported tickets
        if auto_triage and new_tickets:
            import asyncio
            from ..llm_manager import LLMManager
            from ..brain import IntelligenceEngine
            from .. import intelligence as intel
            engine = IntelligenceEngine(LLMManager())
            db2 = SessionLocal()
            for t in new_tickets:
                try:
                    t2 = db2.query(TicketRecord).filter(TicketRecord.id == t.id).first()
                    if t2 and not t2.ai_reasoning:
                        analysis = asyncio.run(engine.process_ticket({
                            "subject": t2.subject,
                            "description": t2.description,
                        }))
                        t2.sentiment = analysis.get("sentiment")
                        t2.category = analysis.get("category")
                        t2.priority = analysis.get("priority")
                        t2.mood = analysis.get("mood")
                        t2.complexity = analysis.get("complexity", 1)
                        t2.ai_reasoning = analysis.get("reasoning")
                        t2.escalation_risk = intel.escalation_risk(t2)
                        if analysis.get("suggested_response"):
                            t2.suggested_response = analysis.get("suggested_response")
                            t2.status = "Awaiting Review"
                        elif analysis.get("action") == "escalate":
                            t2.status = "Escalated"
                        else:
                            t2.status = "Processed"
                        db2.commit()
                        print(f"[fetch] auto-triaged {t2.id[:8]}")

                        # Full pipeline: summarization
                        try:
                            summary = asyncio.run(intel.summarize_ticket(
                                engine.llm, t2
                            ))
                            if summary:
                                t2.summary = summary
                                db2.commit()
                        except Exception as se:
                            print(f"[fetch] summary error on {t2.id[:8]}: {se}")

                        # Full pipeline: resolution plan
                        try:
                            plan = asyncio.run(intel.recommend_resolution(
                                engine.llm, t2
                            ))
                            t2.recommended_solution = __import__("json").dumps(plan)
                            db2.commit()
                        except Exception as re:
                            print(f"[fetch] resolution error on {t2.id[:8]}: {re}")
                except Exception as e:
                    print(f"[fetch] auto-triage error on {t.id}: {e}")
                    db2.rollback()
            db2.close()

    except Exception as e:
        sync_state = db.query(SyncStateRecord).filter(
            SyncStateRecord.provider == adapter.provider_name
        ).first()
        if sync_state:
            sync_state.last_status = "error"
            sync_state.last_error = str(e)
            db.commit()
        result["errors"] += 1
        print(f"[fetch] fatal error: {e}")
    finally:
        db.close()

    return result


def handle_webhook_event(event: WebhookEvent, adapter=None) -> Optional[TicketRecord]:
    adapter = adapter or get_adapter()
    db: Session = SessionLocal()
    try:
        raw = event.raw.get("ticket", event.raw.get("data", {}))
        ext = ExternalTicket(
            external_id=event.external_id,
            subject=raw.get("subject", ""),
            description=raw.get("description_text", raw.get("description", "")) or "",
            reporter=str(raw.get("requester_id", "")),
            priority=adapter.map_priority(raw.get("priority", 3)),
            status=adapter.map_status(raw.get("status", 2)),
            assignee_id=str(raw.get("responder_id")) if raw.get("responder_id") else None,
            updated_at=datetime.fromisoformat(raw["updated_at"]) if raw.get("updated_at") else None,
            url=adapter.build_ticket_url(event.external_id),
        )
        _action, ticket = _upsert_ticket(db, ext, adapter.provider_name, overwrite=True)
        db.commit()
        return ticket
    except Exception as e:
        print(f"[webhook] error: {e}")
        db.rollback()
        return None
    finally:
        db.close()
import uuid as _uuid


def sync_agents_from_external(adapter=None) -> dict:
    """Fetch agents from the external ITSM provider and create / update
    Tickety user accounts.

    Agents have fields: id, first_name, last_name, email, job_title,
    active, occasional, roles, department_ids, …
      • The "List All Agents" endpoint is paginated (per_page up to 100) and
        returns {"agents": […]}.  Sort is created_at desc by default.
      • Rate‑limit sub‑limit: 40–140/min depending on plan.

    This function only imports agents where `active` is True (deactivated
    agents are skipped).  The `occasional` flag is preserved on the Tickety
    UserRecord so the leaderboard can distinguish full‑time from part‑time
    agents later if desired.  Duplicates (same external_source +
    external_assignee_id) are updated in‑place instead of being re‑created.
    """
    adapter = adapter or get_adapter()
    db: Session = SessionLocal()
    result = {"created": 0, "updated": 0, "errors": 0, "total": 0, "skipped_inactive": 0}
    try:
        import asyncio
        raw_agents = asyncio.run(adapter.fetch_agents())
        result["total"] = len(raw_agents)

        for a in raw_agents:
            try:
                ext_id = str(a.get("id", ""))
                if not ext_id:
                    continue

                # Per API docs: active is a boolean; false means the agent has
                # been deactivated and should not receive new tickets / points.
                if a.get("active") is False:
                    result["skipped_inactive"] += 1
                    continue

                mapping = db.query(UserMappingRecord).filter(
                    UserMappingRecord.external_source == adapter.provider_name,
                    UserMappingRecord.external_assignee_id == ext_id,
                ).first()

                name = f"{a.get('first_name','')} {a.get('last_name','')}".strip()
                email = a.get("email", "")
                title = a.get("job_title", "")

                if mapping:
                    user = db.query(UserRecord).filter(
                        UserRecord.id == mapping.tickety_user_id
                    ).first()
                    if user:
                        user.name = name or user.name
                        user.email = email or user.email
                        user.title = title or user.title
                        db.commit()
                        result["updated"] += 1
                else:
                    uid = str(_uuid.uuid4())
                    user = UserRecord(
                        id=uid,
                        name=name or email or f"Agent {ext_id}",
                        email=email,
                        title=title,
                    )
                    db.add(user)
                    db.flush()
                    db.add(UserMappingRecord(
                        tickety_user_id=uid,
                        external_source=adapter.provider_name,
                        external_assignee_id=ext_id,
                    ))
                    db.commit()
                    result["created"] += 1

            except Exception as e:
                print(f"[agents] error processing agent {a.get('id')}: {e}")
                db.rollback()
                result["errors"] += 1

    except Exception as e:
        print(f"[agents] fatal error: {e}")
        result["errors"] += 1
    finally:
        db.close()
    return result
