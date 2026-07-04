import uuid
from datetime import datetime, timedelta
from typing import Any, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..database import (
    SessionLocal, TicketRecord, UserMappingRecord, SyncStateRecord,
    UserRecord,
)
from ..schema import ExternalTicket, WebhookEvent
from ..ticket_vectors import refresh_ticket_documents_background
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

    assignee_id = _resolve_assignee_id(db, provider, ext.assignee_id)
    workflow_status = "Closed" if ext.status.lower() in ("closed", "resolved") else ext.status

    if existing:
        changed = (
            existing.subject != ext.subject
            or existing.description != ext.description
            or existing.reporter != ext.reporter
            or existing.priority != ext.priority
            or existing.external_status != ext.status
            or existing.external_assignee_id != ext.assignee_id
            or existing.external_workspace_id != ext.external_workspace_id
            or existing.external_updated_at != ext.updated_at
            or existing.external_created_at != ext.created_at
            or existing.external_resolved_at != ext.resolved_at
            or existing.external_due_by != ext.due_by
            or existing.external_fr_due_by != ext.fr_due_by
            or existing.assignee_id != assignee_id
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
        existing.external_workspace_id = ext.external_workspace_id
        existing.external_updated_at = ext.updated_at
        existing.external_created_at = ext.created_at
        existing.external_resolved_at = ext.resolved_at
        existing.external_due_by = ext.due_by
        existing.external_fr_due_by = ext.fr_due_by
        existing.external_url = ext.url or existing.external_url
        existing.assignee_id = assignee_id
        existing.workflow_status = workflow_status
        existing.ticket_type = (ext.ticket_type or existing.ticket_type or "incident").lower()
        existing.due_by = ext.due_by or existing.due_by
        existing.resolution_due_at = ext.due_by or existing.resolution_due_at
        existing.response_due_at = ext.fr_due_by or existing.response_due_at
        existing.updated_at = datetime.utcnow()
        if ext.status.lower() in ("closed", "resolved"):
            existing.status = "Closed"
            existing.resolved_at = ext.resolved_at or existing.resolved_at or datetime.utcnow()
        else:
            existing.status = existing.workflow_status or ext.status
        db.commit()
        db.refresh(existing)
        refresh_ticket_documents_background(db, existing)
        return "updated", existing

    new_ticket = TicketRecord(
        id=str(uuid.uuid4()),
        subject=ext.subject,
        description=ext.description,
        reporter=ext.reporter,
        status=workflow_status,
        workflow_status=workflow_status,
        priority=ext.priority,
        ticket_type=(ext.ticket_type or "incident").lower(),
        assignee_id=assignee_id,
        due_by=ext.due_by,
        response_due_at=ext.fr_due_by,
        resolution_due_at=ext.due_by,
        external_source=provider,
        external_id=ext.external_id,
        external_url=ext.url,
        external_status=ext.status,
        external_assignee_id=ext.assignee_id,
        external_workspace_id=ext.external_workspace_id,
        external_updated_at=ext.updated_at,
        external_created_at=ext.created_at,
        external_resolved_at=ext.resolved_at,
        external_due_by=ext.due_by,
        external_fr_due_by=ext.fr_due_by,
        created_at=ext.created_at or datetime.utcnow(),
        resolved_at=ext.resolved_at if ext.status.lower() in ("closed", "resolved") else None,
    )
    db.add(new_ticket)
    db.commit()
    db.refresh(new_ticket)
    refresh_ticket_documents_background(db, new_ticket)
    return "new", new_ticket


def _resolve_assignee_id(db: Session, provider: str, external_assignee_id: Optional[str]) -> Optional[str]:
    if not external_assignee_id:
        return None
    mapping = db.query(UserMappingRecord).filter(
        UserMappingRecord.external_source == provider,
        UserMappingRecord.external_assignee_id == str(external_assignee_id),
    ).first()
    return mapping.tickety_user_id if mapping else None


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

        max_persisted_updated_at = None
        for ext in tickets:
            try:
                action, ticket = _upsert_ticket(db, ext, adapter.provider_name, overwrite=True)
                if action == "new":
                    result["new"] += 1
                elif action == "updated":
                    result["updated"] += 1
                if ticket and ext.updated_at:
                    max_persisted_updated_at = max(max_persisted_updated_at or ext.updated_at, ext.updated_at)
            except Exception as e:
                print(f"[sync] error upserting ticket {ext.external_id}: {e}")
                result["errors"] += 1

        if result["errors"]:
            sync_state.last_status = "error"
            sync_state.last_error = "One or more tickets failed to persist; cursor not advanced"
        else:
            if max_persisted_updated_at:
                sync_state.last_synced_at = max_persisted_updated_at - timedelta(seconds=5)
            elif not tickets:
                sync_state.last_synced_at = datetime.utcnow()
            sync_state.last_status = "success"
            sync_state.last_error = None
        sync_state.total_synced += result["new"] + result["updated"]
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

        from .. import settings as settings_module
        auto_triage = settings_module.automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE")
        auto_summary = settings_module.automation_enabled("AUTO_SUMMARIZE_ENABLED")
        auto_resolution = settings_module.automation_enabled("AUTO_RESOLVE_ENABLED")
        new_tickets: list = []  # collect for auto-triage

        max_persisted_updated_at = None
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
                if ticket and ext.updated_at:
                    max_persisted_updated_at = max(max_persisted_updated_at or ext.updated_at, ext.updated_at)
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
        if result["errors"]:
            sync_state.last_status = "error"
            sync_state.last_error = "One or more fetched tickets failed to persist; cursor not advanced"
        else:
            if max_persisted_updated_at and (not sync_state.last_synced_at or since <= sync_state.last_synced_at):
                sync_state.last_synced_at = max_persisted_updated_at - timedelta(seconds=5)
            elif not tickets and (not sync_state.last_synced_at or since <= sync_state.last_synced_at):
                sync_state.last_synced_at = datetime.utcnow()
            sync_state.last_status = "success"
            sync_state.last_error = None
        sync_state.total_synced += result["new"] + result["updated"]
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
                            t2.ai_review_state = "Awaiting Review"
                            if (t2.workflow_status or t2.status or "New").lower() in {"new", "open", "processed"}:
                                t2.workflow_status = "Awaiting Review"
                        elif analysis.get("action") == "escalate":
                            t2.ai_review_state = "Escalated"
                            t2.workflow_status = "Escalated"
                        else:
                            t2.ai_review_state = "Processed"
                            t2.workflow_status = t2.workflow_status or t2.status or "Open"
                        t2.status = t2.workflow_status or t2.status
                        db2.commit()
                        print(f"[fetch] auto-triaged {t2.id[:8]}")

                        if auto_summary:
                            try:
                                summary = asyncio.run(intel.summarize_ticket(
                                    engine.llm, t2
                                ))
                                if summary:
                                    t2.summary = summary
                                    db2.commit()
                            except Exception as se:
                                print(f"[fetch] summary error on {t2.id[:8]}: {se}")

                        if auto_resolution:
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
            external_workspace_id=str(raw.get("workspace_id")) if raw.get("workspace_id") is not None else None,
            updated_at=adapter._parse_datetime(raw.get("updated_at")) if hasattr(adapter, "_parse_datetime") else (
                datetime.fromisoformat(raw["updated_at"]) if raw.get("updated_at") else None
            ),
            created_at=adapter._parse_datetime(raw.get("created_at")) if hasattr(adapter, "_parse_datetime") else None,
            resolved_at=adapter._parse_datetime(raw.get("resolved_at") or raw.get("closed_at")) if hasattr(adapter, "_parse_datetime") else None,
            due_by=adapter._parse_datetime(raw.get("due_by")) if hasattr(adapter, "_parse_datetime") else None,
            fr_due_by=adapter._parse_datetime(raw.get("fr_due_by")) if hasattr(adapter, "_parse_datetime") else None,
            ticket_type=str(raw.get("type") or raw.get("ticket_type") or ""),
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


def _external_agent_value(agent: dict, *keys: str) -> str:
    for key in keys:
        value = agent.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _external_agent_active(agent: dict) -> bool:
    value = agent.get("active")
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "inactive"}
    return value is not False


def _normalize_external_agent(agent: dict) -> dict[str, Any]:
    ext_id = _external_agent_value(
        agent,
        "id",
        "accountId",
        "account_id",
        "user_id",
    )
    first = _external_agent_value(agent, "first_name", "firstName")
    last = _external_agent_value(agent, "last_name", "lastName")
    full_name = _external_agent_value(
        agent,
        "name",
        "display_name",
        "displayName",
        "full_name",
        "fullName",
    )
    name = full_name or f"{first} {last}".strip()
    email = _external_agent_value(agent, "email", "emailAddress", "mail").lower()
    title = _external_agent_value(agent, "job_title", "jobTitle", "title", "accountType")
    return {
        "id": ext_id,
        "name": name or email or (f"Agent {ext_id}" if ext_id else "Agent"),
        "email": email,
        "title": title,
        "active": _external_agent_active(agent),
    }


def _find_user_by_email(db: Session, email: str) -> Optional[UserRecord]:
    if not email:
        return None
    return db.query(UserRecord).filter(func.lower(UserRecord.email) == email).first()


def _find_unique_user_by_name(db: Session, name: str) -> Optional[UserRecord]:
    if not name:
        return None
    users = db.query(UserRecord).filter(func.lower(UserRecord.name) == name.lower()).all()
    return users[0] if len(users) == 1 else None


def _apply_external_agent_profile(user: UserRecord, agent: dict[str, Any]) -> bool:
    changed = False
    if agent["name"] and user.name != agent["name"]:
        user.name = agent["name"]
        changed = True
    if agent["email"] and (user.email or "").strip().lower() != agent["email"]:
        user.email = agent["email"]
        changed = True
    if agent["title"] and user.title != agent["title"]:
        user.title = agent["title"]
        changed = True
    return changed


def _create_external_agent_user(db: Session, agent: dict[str, Any]) -> UserRecord:
    user = UserRecord(
        id=str(uuid.uuid4()),
        name=agent["name"],
        email=agent["email"],
        title=agent["title"],
    )
    db.add(user)
    db.flush()
    return user


def _reconcile_ticket_assignees(db: Session, provider: str) -> int:
    rows = db.query(TicketRecord, UserMappingRecord.tickety_user_id).join(
        UserMappingRecord,
        and_(
            TicketRecord.external_source == UserMappingRecord.external_source,
            TicketRecord.external_assignee_id == UserMappingRecord.external_assignee_id,
        ),
    ).filter(
        TicketRecord.external_source == provider,
        TicketRecord.external_assignee_id.isnot(None),
    ).all()
    updated = 0
    for ticket, tickety_user_id in rows:
        if ticket.assignee_id != tickety_user_id:
            ticket.assignee_id = tickety_user_id
            ticket.updated_at = datetime.utcnow()
            updated += 1
    if updated:
        db.commit()
    return updated


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
    result = {
        "created": 0,
        "updated": 0,
        "remapped": 0,
        "errors": 0,
        "total": 0,
        "skipped_inactive": 0,
        "tickets_reassigned": 0,
    }
    try:
        import asyncio
        raw_agents = asyncio.run(adapter.fetch_agents())
        result["total"] = len(raw_agents)

        for raw_agent in raw_agents:
            try:
                agent = _normalize_external_agent(raw_agent)
                ext_id = agent["id"]
                if not ext_id:
                    continue

                # Per API docs: active is a boolean; false means the agent has
                # been deactivated and should not receive new tickets / points.
                if not agent["active"]:
                    result["skipped_inactive"] += 1
                    continue

                mapping = db.query(UserMappingRecord).filter(
                    UserMappingRecord.external_source == adapter.provider_name,
                    UserMappingRecord.external_assignee_id == ext_id,
                ).first()

                matched_user = _find_user_by_email(db, agent["email"])
                if not matched_user and not agent["email"]:
                    matched_user = _find_unique_user_by_name(db, agent["name"])
                user = None
                created_user = False
                remapped = False

                if mapping:
                    mapped_user = db.query(UserRecord).filter(
                        UserRecord.id == mapping.tickety_user_id
                    ).first()

                    mapped_email = (mapped_user.email or "").strip().lower() if mapped_user else ""
                    if matched_user and matched_user.id != mapping.tickety_user_id and (
                        (agent["email"] and mapped_email != agent["email"])
                        or (not agent["email"] and not mapped_user)
                    ):
                        user = matched_user
                        mapping.tickety_user_id = user.id
                        remapped = True
                    else:
                        user = mapped_user

                    if not user:
                        user = matched_user or _create_external_agent_user(db, agent)
                        created_user = matched_user is None
                        if mapping.tickety_user_id != user.id:
                            mapping.tickety_user_id = user.id
                            remapped = True
                else:
                    user = matched_user or _create_external_agent_user(db, agent)
                    created_user = matched_user is None
                    db.add(UserMappingRecord(
                        tickety_user_id=user.id,
                        external_source=adapter.provider_name,
                        external_assignee_id=ext_id,
                    ))

                profile_changed = _apply_external_agent_profile(user, agent)
                db.commit()

                if created_user:
                    result["created"] += 1
                elif remapped:
                    result["remapped"] += 1
                elif profile_changed or mapping:
                    result["updated"] += 1

            except Exception as e:
                print(f"[agents] error processing agent {raw_agent.get('id') or raw_agent.get('accountId')}: {e}")
                db.rollback()
                result["errors"] += 1

        result["tickets_reassigned"] = _reconcile_ticket_assignees(db, adapter.provider_name)

    except Exception as e:
        print(f"[agents] fatal error: {e}")
        result["errors"] += 1
    finally:
        db.close()
    return result
