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
# Kept as a module attribute for compatibility with integrations/tests that
# patch it. External persistence never promotes un-indexed provider text into
# shared RAG: only tickets that already have evidence documents are refreshed
# when their provider content changes (see refresh_ticket_documents_if_indexed).
from ..ticket_vectors import (
    refresh_ticket_documents_background,
    refresh_ticket_documents_if_indexed,
)
from ..ai_state import invalidate_ticket_ai, invalidate_ticket_resolution
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
        analysis_input_changed = (
            existing.subject != ext.subject or existing.description != ext.description
        )
        resolution_input_changed = existing.priority != ext.priority
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
        if analysis_input_changed:
            invalidate_ticket_ai(existing)
        if resolution_input_changed:
            invalidate_ticket_resolution(existing)
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
        if analysis_input_changed:
            # Keep promoted RAG evidence in sync when provider text changes;
            # tickets without indexed documents are never auto-promoted.
            refresh_ticket_documents_if_indexed(db, existing)
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
                print(f"[sync] ticket upsert failed kind={type(e).__name__}")
                # A flush/commit failure leaves the SQLAlchemy session in a
                # failed transaction. Reset it before processing the next
                # ticket so one bad record cannot poison the rest of the
                # batch or prevent the final sync-state update.
                db.rollback()
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
            sync_state.last_error = f"sync_failed:{type(e).__name__}"
            db.commit()
        result["errors"] += 1
        print(f"[sync] fatal error kind={type(e).__name__}")
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
                elif action == "updated":
                    result["updated"] += 1
                elif action == "skipped":
                    result["skipped"] += 1
                if ticket and ext.updated_at:
                    max_persisted_updated_at = max(max_persisted_updated_at or ext.updated_at, ext.updated_at)
            except Exception as e:
                print(f"[fetch] ticket upsert failed kind={type(e).__name__}")
                # Roll back the aborted transaction so a single poison ticket
                # cannot stall every subsequent upsert (psycopg2 leaves the
                # transaction aborted after a failed statement).
                db.rollback()
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

        # NOTE: newly imported external tickets are deliberately NOT queued or
        # auto-processed here. Provider-authenticated sync proves transport
        # integrity, not that requester-controlled ticket text is safe AI
        # input; tickets must be explicitly promoted by an authenticated
        # workflow (see sync_worker._auto_triage_job for the same policy).

    except Exception as e:
        try:
            db.rollback()
            sync_state = db.query(SyncStateRecord).filter(
                SyncStateRecord.provider == adapter.provider_name
            ).first()
            if sync_state:
                sync_state.last_status = "error"
                sync_state.last_error = f"fetch_failed:{type(e).__name__}"
                db.commit()
        except Exception as state_exc:
            print(f"[fetch] failed to record sync state kind={type(state_exc).__name__}")
        result["errors"] += 1
        print(f"[fetch] fatal error kind={type(e).__name__}")
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
        print(f"[webhook] apply failed kind={type(e).__name__}")
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


def _find_users_by_email(db: Session, email: str) -> list[UserRecord]:
    if not email:
        return []
    return db.query(UserRecord).filter(func.lower(UserRecord.email) == email).all()


def _find_user_by_email(db: Session, email: str) -> Optional[UserRecord]:
    users = _find_users_by_email(db, email)
    return users[0] if len(users) == 1 else None


def _find_users_by_name(db: Session, name: str) -> list[UserRecord]:
    if not name:
        return []
    return db.query(UserRecord).filter(func.lower(UserRecord.name) == name.lower()).all()


def _find_unique_user_by_name(db: Session, name: str) -> Optional[UserRecord]:
    users = _find_users_by_name(db, name)
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


def _empty_agent_sync_result() -> dict:
    return {
        "created": 0,
        "updated": 0,
        "merged": 0,
        "remapped": 0,
        "missing": 0,
        "conflicts": 0,
        "errors": 0,
        "error_details": [],
        "conflict_details": [],
        "missing_details": [],
        "total": 0,
        "skipped_inactive": 0,
        "tickets_reassigned": 0,
    }


def _agent_sync_options(options: Optional[dict[str, Any]]) -> dict[str, bool]:
    options = options or {}
    mode = str(options.get("mode") or "sync").strip().lower()
    merge_mode = mode in {"merge", "merge_reconcile", "reconcile"}
    return {
        "create_missing": bool(options.get("create_missing", True)),
        "merge_existing": bool(options.get("merge_existing", merge_mode)),
        "update_profiles": bool(options.get("update_profiles", True)),
        "match_by_name": bool(options.get("match_by_name", merge_mode)),
        "reassign_tickets": bool(options.get("reassign_tickets", True)),
    }


def _limited_append(items: list[str], detail: str, limit: int = 12) -> None:
    if len(items) < limit:
        items.append(detail)


def _find_agent_match(
    db: Session,
    agent: dict[str, Any],
    *,
    match_by_name: bool,
) -> tuple[Optional[UserRecord], Optional[str], Optional[str]]:
    email_matches = _find_users_by_email(db, agent["email"])
    if len(email_matches) == 1:
        return email_matches[0], "email", None
    if len(email_matches) > 1:
        return None, None, (
            f"{agent['name']} matches {len(email_matches)} Tickety users with email {agent['email']}; "
            "merge skipped"
        )

    if match_by_name and not agent["email"]:
        name_matches = _find_users_by_name(db, agent["name"])
        if len(name_matches) == 1:
            return name_matches[0], "name", None
        if len(name_matches) > 1:
            return None, None, (
                f"{agent['name']} matches {len(name_matches)} Tickety users by name; merge skipped"
            )

    return None, None, None


def _import_external_agents(adapter, raw_agents: list[dict[str, Any]], options: Optional[dict[str, Any]] = None) -> dict:
    sync_options = _agent_sync_options(options)
    db: Session = SessionLocal()
    result = _empty_agent_sync_result()
    result["options"] = sync_options
    try:
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

                matched_user, match_reason, conflict = _find_agent_match(
                    db,
                    agent,
                    match_by_name=sync_options["match_by_name"],
                )
                if conflict:
                    result["conflicts"] += 1
                    _limited_append(result["conflict_details"], conflict)
                    continue

                user = None
                created_user = False
                merged_user = False
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
                        if sync_options["merge_existing"]:
                            user = matched_user
                            mapping.tickety_user_id = user.id
                            remapped = True
                        else:
                            result["conflicts"] += 1
                            _limited_append(
                                result["conflict_details"],
                                f"{agent['name']} is mapped to one Tickety user but matches another by {match_reason}; enable merge to reconcile",
                            )
                            continue
                    else:
                        user = mapped_user

                    if not user:
                        if matched_user and sync_options["merge_existing"]:
                            user = matched_user
                            merged_user = True
                        elif matched_user:
                            result["conflicts"] += 1
                            _limited_append(
                                result["conflict_details"],
                                f"{agent['name']} matches an existing Tickety user by {match_reason}; enable merge to link the accounts",
                            )
                            continue
                        elif sync_options["create_missing"]:
                            user = _create_external_agent_user(db, agent)
                            created_user = True
                        else:
                            result["missing"] += 1
                            _limited_append(result["missing_details"], f"{agent['name']} has no Tickety account")
                            continue
                        if mapping.tickety_user_id != user.id:
                            mapping.tickety_user_id = user.id
                            remapped = True
                else:
                    if matched_user and sync_options["merge_existing"]:
                        user = matched_user
                        merged_user = True
                    elif matched_user:
                        result["conflicts"] += 1
                        _limited_append(
                            result["conflict_details"],
                            f"{agent['name']} matches an existing Tickety user by {match_reason}; enable merge to link the accounts",
                        )
                        continue
                    elif sync_options["create_missing"]:
                        user = _create_external_agent_user(db, agent)
                        created_user = True
                    else:
                        result["missing"] += 1
                        _limited_append(result["missing_details"], f"{agent['name']} has no Tickety account")
                        continue
                    db.add(UserMappingRecord(
                        tickety_user_id=user.id,
                        external_source=adapter.provider_name,
                        external_assignee_id=ext_id,
                    ))

                profile_changed = _apply_external_agent_profile(user, agent) if sync_options["update_profiles"] else False
                db.commit()

                if created_user:
                    result["created"] += 1
                if merged_user:
                    result["merged"] += 1
                elif remapped:
                    result["remapped"] += 1
                elif profile_changed:
                    result["updated"] += 1

            except Exception as e:
                agent_id = (
                    raw_agent.get("id") or raw_agent.get("accountId")
                    if isinstance(raw_agent, dict)
                    else "unknown"
                )
                detail = f"agent_processing_failed:{type(e).__name__}"
                print(f"[agents] processing failed kind={type(e).__name__}")
                db.rollback()
                result["errors"] += 1
                result["error_details"].append(detail)

        if sync_options["reassign_tickets"]:
            result["tickets_reassigned"] = _reconcile_ticket_assignees(db, adapter.provider_name)

    except Exception as e:
        print(f"[agents] fatal error kind={type(e).__name__}")
        result["errors"] += 1
        result["error_details"].append(f"agent_sync_failed:{type(e).__name__}")
    finally:
        db.close()
    return result


async def async_sync_agents_from_external(adapter=None, options: Optional[dict[str, Any]] = None) -> dict:
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
    try:
        raw_agents = await adapter.fetch_agents()
    except Exception as e:
        print(f"[agents] fatal error kind={type(e).__name__}")
        result = _empty_agent_sync_result()
        result["errors"] += 1
        result["error_details"].append(f"agent_fetch_failed:{type(e).__name__}")
        return result
    return _import_external_agents(adapter, raw_agents, options=options)


def sync_agents_from_external(adapter=None, options: Optional[dict[str, Any]] = None) -> dict:
    adapter = adapter or get_adapter()
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_sync_agents_from_external(adapter, options=options))

    raise RuntimeError(
        "sync_agents_from_external cannot run inside an active event loop; "
        "use async_sync_agents_from_external instead"
    )
