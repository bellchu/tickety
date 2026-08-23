import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from ..database import (
    ExternalUserRecord, SessionLocal, TicketRecord, SyncStateRecord,
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


def _project_source_status(source_status: str) -> tuple[str, str, str]:
    """Project one provider status into external, workflow, and display state."""
    workflow_status = (
        "Closed"
        if source_status.lower() in ("closed", "resolved")
        else source_status
    )
    return source_status, workflow_status, workflow_status


def _upsert_ticket(
    db: Session,
    ext: ExternalTicket,
    provider: str,
    overwrite: bool = False,
    binding_id: str = "legacy",
) -> tuple[str, Optional[TicketRecord]]:
    """Upsert an external ticket. Returns (action, ticket) where action is
    one of "new" / "updated" / "skipped". Source status is authoritative and
    is always reconciled. When `overwrite` is False, other fields on an
    existing local ticket remain untouched."""
    existing = db.query(TicketRecord).filter(
        TicketRecord.binding_id == binding_id,
        TicketRecord.external_source == provider,
        TicketRecord.external_id == ext.external_id,
    ).first()

    authoritative_status = _project_source_status(ext.status)
    external_status, workflow_status, display_status = authoritative_status

    if existing:
        source_status_changed = (
            existing.external_status,
            existing.workflow_status,
            existing.status,
        ) != authoritative_status
        if not overwrite:
            if not source_status_changed:
                return "skipped", None
            existing.external_status = external_status
            existing.workflow_status = workflow_status
            existing.status = display_status
            if ext.updated_at is not None:
                existing.external_updated_at = ext.updated_at
            existing.external_resolved_at = ext.resolved_at
            existing.updated_at = datetime.utcnow()
            if ext.status.lower() in ("closed", "resolved"):
                existing.resolved_at = (
                    ext.resolved_at or existing.resolved_at or datetime.utcnow()
                )
            db.commit()
            db.refresh(existing)
            refresh_ticket_documents_if_indexed(db, existing)
            return "updated", existing

        analysis_input_changed = (
            existing.subject != ext.subject or existing.description != ext.description
        )
        resolution_input_changed = existing.priority != ext.priority
        changed = (
            existing.subject != ext.subject
            or existing.description != ext.description
            or existing.reporter != ext.reporter
            or existing.priority != ext.priority
            or source_status_changed
            or existing.external_assignee_id != ext.assignee_id
            or existing.external_workspace_id != ext.external_workspace_id
            or existing.external_updated_at != ext.updated_at
            or existing.external_created_at != ext.created_at
            or existing.external_resolved_at != ext.resolved_at
            or existing.external_due_by != ext.due_by
            or existing.external_fr_due_by != ext.fr_due_by
            or existing.ticket_type != (ext.ticket_type or existing.ticket_type or "incident").lower()
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
        existing.external_status = external_status
        existing.external_assignee_id = ext.assignee_id
        existing.external_workspace_id = ext.external_workspace_id
        existing.external_updated_at = ext.updated_at
        existing.external_created_at = ext.created_at
        existing.external_resolved_at = ext.resolved_at
        existing.external_due_by = ext.due_by
        existing.external_fr_due_by = ext.fr_due_by
        existing.external_url = ext.url or existing.external_url
        existing.workflow_status = workflow_status
        existing.ticket_type = (ext.ticket_type or existing.ticket_type or "incident").lower()
        existing.due_by = ext.due_by or existing.due_by
        existing.resolution_due_at = ext.due_by or existing.resolution_due_at
        existing.response_due_at = ext.fr_due_by or existing.response_due_at
        existing.updated_at = datetime.utcnow()
        if ext.status.lower() in ("closed", "resolved"):
            existing.status = display_status
            existing.resolved_at = ext.resolved_at or existing.resolved_at or datetime.utcnow()
        else:
            existing.status = display_status
        db.commit()
        db.refresh(existing)
        # Keep already-promoted evidence current for every provider update.
        # The refresh gate only admits the ticket's own document, so comments
        # alone never promote requester-controlled ticket text into shared RAG.
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
        due_by=ext.due_by,
        response_due_at=ext.fr_due_by,
        resolution_due_at=ext.due_by,
        external_source=provider,
        binding_id=binding_id,
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


def _existing_external_ticket_states(
    db: Session,
    provider: str,
    binding_id: str = "legacy",
) -> dict[str, tuple[Optional[str], Optional[str], Optional[str]]]:
    """Return existing source/local status state keyed by external ID.

    Manual fetch uses this to skip unchanged existing tickets without issuing
    a database query for every fetched ticket, while still reconciling any
    source status change even when full overwrite is disabled.
    """
    rows = db.query(
        TicketRecord.external_id,
        TicketRecord.external_status,
        TicketRecord.workflow_status,
        TicketRecord.status,
    ).filter(
        TicketRecord.binding_id == binding_id,
        TicketRecord.external_source == provider,
        TicketRecord.external_id.isnot(None),
    ).all()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


def sync_tickets_from_external(adapter=None, *, binding_id: str = "legacy") -> dict:
    adapter = adapter or get_adapter()
    db: Session = SessionLocal()
    result = {"new": 0, "updated": 0, "errors": 0}
    try:
        sync_state = db.query(SyncStateRecord).filter(
            SyncStateRecord.binding_id == binding_id,
            SyncStateRecord.provider == adapter.provider_name
        ).first()
        if not sync_state:
            sync_state = SyncStateRecord(
                binding_id=binding_id,
                provider=adapter.provider_name,
                last_status="running",
            )
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
                action, ticket = _upsert_ticket(
                    db,
                    ext,
                    adapter.provider_name,
                    overwrite=True,
                    binding_id=binding_id,
                )
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
        # The failed operation may have left the session in SQLAlchemy's
        # pending-rollback state.  Clear it before looking up the sync state;
        # otherwise the error-reporting query itself can mask the original
        # sync failure and leave the binding stuck in "running".
        try:
            db.rollback()
            sync_state = db.query(SyncStateRecord).filter(
                SyncStateRecord.binding_id == binding_id,
                SyncStateRecord.provider == adapter.provider_name
            ).first()
            if sync_state:
                sync_state.last_status = "error"
                sync_state.last_error = f"sync_failed:{type(e).__name__}"
                db.commit()
        except Exception as state_exc:
            # Preserve the initiating failure in logs even when the database
            # is unavailable for the best-effort status update.
            try:
                db.rollback()
            except Exception:
                pass
            print(
                "[sync] failed to record fatal sync state "
                f"original={type(e).__name__} state_update={type(state_exc).__name__}"
            )
        result["errors"] += 1
        print(f"[sync] fatal error kind={type(e).__name__}")
    finally:
        db.close()

    return result


def fetch_tickets_by_days(
    adapter=None,
    days: int = 7,
    overwrite: bool = False,
    *,
    binding_id: str = "legacy",
) -> dict:
    """Manually fetch all tickets updated in the last `days` days from the
    external ITSM provider, walking every page while respecting rate limits.

    Source status is always reconciled for tickets already imported (matched
    by external_source + external_id). With overwrite=False, all other local
    fields are preserved. Pass overwrite=True to force-refresh every provider
    field on existing records.
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

        # Pre-load status state once so unchanged existing tickets avoid an
        # extra DB query while changed source statuses still reach the upsert.
        existing_states = _existing_external_ticket_states(
            db, adapter.provider_name, binding_id
        )

        max_persisted_updated_at = None
        for ext in tickets:
            try:
                existing_state = existing_states.get(ext.external_id)
                if existing_state is not None and not overwrite:
                    authoritative_state = _project_source_status(ext.status)
                    if existing_state == authoritative_state:
                        result["skipped"] += 1
                        continue
                action, ticket = _upsert_ticket(
                    db,
                    ext,
                    adapter.provider_name,
                    overwrite=overwrite,
                    binding_id=binding_id,
                )
                if action == "new":
                    result["new"] += 1
                elif action == "updated":
                    result["updated"] += 1
                elif action == "skipped":
                    result["skipped"] += 1
                if ticket and ext.updated_at:
                    max_persisted_updated_at = max(max_persisted_updated_at or ext.updated_at, ext.updated_at)
                if ticket:
                    existing_states[ext.external_id] = (
                        ticket.external_status,
                        ticket.workflow_status,
                        ticket.status,
                    )
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
            SyncStateRecord.binding_id == binding_id,
            SyncStateRecord.provider == adapter.provider_name
        ).first()
        if not sync_state:
            sync_state = SyncStateRecord(
                binding_id=binding_id,
                provider=adapter.provider_name,
                total_synced=0,
            )
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
                SyncStateRecord.binding_id == binding_id,
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


def handle_webhook_event(
    event: WebhookEvent,
    adapter=None,
    *,
    binding_id: str = "legacy",
) -> Optional[TicketRecord]:
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
        _action, ticket = _upsert_ticket(
            db,
            ext,
            adapter.provider_name,
            overwrite=True,
            binding_id=binding_id,
        )
        db.commit()
        return ticket
    except Exception as e:
        print(f"[webhook] apply failed kind={type(e).__name__}")
        db.rollback()
        return None
    finally:
        db.close()


def _external_user_value(user: dict, *keys: str) -> str:
    for key in keys:
        value = user.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _external_user_active(user: dict) -> bool:
    value = user.get("active")
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "inactive"}
    return value is not False


def _external_user_type(user: dict) -> str:
    explicit = _external_user_value(user, "user_type", "type").lower()
    if explicit in {"agent", "requester"}:
        return explicit
    if user.get("is_agent") is False:
        return "requester"
    return "agent"


def _external_profile(user: dict) -> dict[str, Any]:
    """Keep a bounded, non-authentication subset of provider profile data."""
    allowed = (
        "belongs_to_workspace_ids",
        "department_ids",
        "language",
        "location_id",
        "occasional",
        "role_ids",
        "roles",
        "time_zone",
    )
    return {key: user[key] for key in allowed if user.get(key) is not None}


def _external_source_updated_at(user: dict) -> Optional[datetime]:
    value = user.get("updated_at") or user.get("updatedAt")
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc).replace(tzinfo=None)
            if value.tzinfo
            else value
        )
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _normalize_external_user(user: dict) -> dict[str, Any]:
    ext_id = _external_user_value(user, "id", "accountId", "account_id", "user_id")
    first = _external_user_value(user, "first_name", "firstName")
    last = _external_user_value(user, "last_name", "lastName")
    full_name = _external_user_value(
        user, "name", "display_name", "displayName", "full_name", "fullName"
    )
    name = full_name or f"{first} {last}".strip()
    email = _external_user_value(
        user, "email", "primary_email", "emailAddress", "mail"
    ).lower()
    title = _external_user_value(user, "job_title", "jobTitle", "title", "accountType")
    return {
        "id": ext_id,
        "user_type": _external_user_type(user),
        "name": name or email or (f"External user {ext_id}" if ext_id else "External user"),
        "email": email,
        "title": title,
        "active": _external_user_active(user),
        "profile_json": json.dumps(
            _external_profile(user), sort_keys=True, separators=(",", ":")
        ),
        "source_updated_at": _external_source_updated_at(user),
    }


def _empty_external_user_sync_result() -> dict:
    return {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "deactivated": 0,
        "errors": 0,
        "error_details": [],
        "total": 0,
    }


def _limited_append(items: list[str], detail: str, limit: int = 12) -> None:
    if len(items) < limit:
        items.append(detail)


def _import_external_users(
    adapter,
    raw_users: list[dict[str, Any]],
    *,
    binding_id: str = "legacy",
) -> dict:
    """Store provider users only in the external directory security domain."""
    db: Session = SessionLocal()
    result = _empty_external_user_sync_result()
    seen: set[tuple[str, str]] = set()
    try:
        result["total"] = len(raw_users)
        for raw_user in raw_users:
            try:
                user = _normalize_external_user(raw_user)
                ext_id = user["id"]
                if not ext_id:
                    raise ValueError("external user has no provider id")
                identity = (user["user_type"], ext_id)
                seen.add(identity)
                record = db.query(ExternalUserRecord).filter(
                    ExternalUserRecord.binding_id == binding_id,
                    ExternalUserRecord.provider == adapter.provider_name,
                    ExternalUserRecord.user_type == user["user_type"],
                    ExternalUserRecord.external_id == ext_id,
                ).first()
                now = datetime.utcnow()
                if record is None:
                    record = ExternalUserRecord(
                        id=str(uuid.uuid4()),
                        binding_id=binding_id,
                        provider=adapter.provider_name,
                        external_id=ext_id,
                        user_type=user["user_type"],
                        name=user["name"],
                        email=user["email"] or None,
                        title=user["title"] or None,
                        active=user["active"],
                        profile_json=user["profile_json"],
                        source_updated_at=user["source_updated_at"],
                        fetched_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(record)
                    result["created"] += 1
                else:
                    values = {
                        "name": user["name"],
                        "email": user["email"] or None,
                        "title": user["title"] or None,
                        "active": user["active"],
                        "profile_json": user["profile_json"],
                        "source_updated_at": user["source_updated_at"],
                    }
                    changed = any(
                        getattr(record, key) != value for key, value in values.items()
                    )
                    for key, value in values.items():
                        setattr(record, key, value)
                    record.fetched_at = now
                    if changed:
                        record.updated_at = now
                        result["updated"] += 1
                    else:
                        result["unchanged"] += 1
                db.commit()
            except Exception as exc:
                print(f"[external-users] processing failed kind={type(exc).__name__}")
                db.rollback()
                result["errors"] += 1
                _limited_append(
                    result["error_details"],
                    f"external_user_processing_failed:{type(exc).__name__}",
                )

        # Only a complete, error-free directory read can prove that a formerly
        # active provider identity disappeared.
        if not result["errors"]:
            existing = db.query(ExternalUserRecord).filter(
                ExternalUserRecord.binding_id == binding_id,
                ExternalUserRecord.provider == adapter.provider_name,
                ExternalUserRecord.active.is_(True),
            ).all()
            now = datetime.utcnow()
            for record in existing:
                if (record.user_type, record.external_id) not in seen:
                    record.active = False
                    record.fetched_at = now
                    record.updated_at = now
                    result["deactivated"] += 1
            db.commit()
    except Exception as exc:
        print(f"[external-users] fatal error kind={type(exc).__name__}")
        db.rollback()
        result["errors"] += 1
        _limited_append(
            result["error_details"],
            f"external_user_sync_failed:{type(exc).__name__}",
        )
    finally:
        db.close()
    return result


async def async_sync_external_users(
    adapter=None,
    *,
    binding_id: str = "legacy",
) -> dict:
    """Refresh external profiles without creating or updating Tickety users."""
    adapter = adapter or get_adapter()
    try:
        raw_users = await adapter.fetch_external_users()
    except Exception as exc:
        print(f"[external-users] fetch failed kind={type(exc).__name__}")
        result = _empty_external_user_sync_result()
        result["errors"] += 1
        result["error_details"].append(
            f"external_user_fetch_failed:{type(exc).__name__}"
        )
        return result
    return _import_external_users(adapter, raw_users, binding_id=binding_id)


def sync_external_users(
    adapter=None,
    *,
    binding_id: str = "legacy",
) -> dict:
    adapter = adapter or get_adapter()
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            async_sync_external_users(adapter, binding_id=binding_id)
        )

    raise RuntimeError(
        "sync_external_users cannot run inside an active event loop; "
        "use async_sync_external_users instead"
    )
