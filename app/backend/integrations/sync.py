import json
import hashlib
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import (
    AIArtifactRecord,
    ExternalActivityRecord,
    ExternalConversationRecord,
    ExternalTicketContextRecord,
    ExternalUserRecord,
    SessionLocal,
    SyncStateRecord,
    TicketCommentRecord,
    TicketRecord,
)
from ..schema import ExternalConversation, ExternalTicket, WebhookEvent
# Kept as a module attribute for compatibility with integrations/tests that
# patch it. External persistence never promotes un-indexed provider text into
# shared RAG: only tickets that already have evidence documents are refreshed
# when their provider content changes (see refresh_ticket_documents_if_indexed).
from ..ticket_vectors import (
    refresh_ticket_documents_background,
    refresh_ticket_documents_if_indexed,
)
from ..ai_state import invalidate_ticket_ai, invalidate_ticket_resolution
from .. import settings as settings_module
from .registry import get_adapter


def _enabled_analysis_artifacts(*, downstream_only: bool = False) -> set[str]:
    """Resolve the existing automation flags into explicit worker artifacts."""
    artifacts: set[str] = set()
    if not downstream_only:
        if settings_module.automation_enabled("AUTO_TRIAGE_ENABLED", "AUTO_TRIAGE"):
            artifacts.add("triage")
        if settings_module.automation_enabled("AUTO_SUMMARIZE_ENABLED"):
            artifacts.add("summary")
    if settings_module.automation_enabled("AUTO_ROUTE_ENABLED"):
        artifacts.add("route")
    if settings_module.automation_enabled("AUTO_RESOLVE_ENABLED"):
        artifacts.add("resolution")
    return artifacts


def _queue_analysis(ticket: TicketRecord, artifacts: set[str]) -> None:
    if not artifacts:
        return
    if ticket.ai_status == "queued":
        artifacts.update(
            item for item in (ticket.ai_requested_artifacts or "").split(",") if item
        )
    ticket.ai_status = "queued"
    ticket.ai_requested_artifacts = ",".join(sorted(artifacts))
    ticket.ai_next_attempt_at = None
    ticket.ai_error = None


AUTOMATIC_AI_LOOKBACK_DAYS = 7


def _missing_automatic_artifacts(
    ticket: TicketRecord,
    enabled: set[str],
) -> set[str]:
    """Return only durable AI gaps that can be completed by the worker.

    Routing is deterministic and has no persisted artifact of its own, so it
    accompanies a generated artifact instead of making an otherwise-complete
    ticket recur in every lookback sweep.
    """
    generated = enabled & {"triage", "summary", "resolution"}
    if not generated:
        return set()
    stale = (ticket.ai_status or "").strip().lower() in {
        "stale",
        "legacy_stale",
        "provenance_unknown",
    }
    missing: set[str] = set()
    if "triage" in generated and (stale or not ticket.ai_reasoning):
        missing.add("triage")
    if "summary" in generated and (stale or not ticket.summary):
        missing.add("summary")
    if "resolution" in generated and (stale or not ticket.recommended_solution):
        missing.add("resolution")
    if missing and "route" in enabled:
        missing.add("route")
    return missing


def queue_recent_automatic_ai(
    db: Session,
    *,
    now: Optional[datetime] = None,
    batch_size: int = 5,
) -> dict[str, int]:
    """Queue missing AI work for external tickets active in the last 7 days.

    The integration's explicit automatic-AI switch remains the authorization
    boundary. This rolling, bounded scanner is deliberately separate from the
    immutable realtime cutover so existing activity evidence is not rewritten.
    Repeated calls are idempotent because queued/running/terminal rows are not
    selected and completed artifacts are detected before enqueueing.
    """
    enabled = _enabled_analysis_artifacts()
    generated = enabled & {"triage", "summary", "resolution"}
    limit = max(1, min(int(batch_size), 25))
    result = {"lookback_days": AUTOMATIC_AI_LOOKBACK_DAYS, "queued": 0}
    if not generated:
        return result

    current = _utc_naive(now) or datetime.utcnow()
    cutoff = current - timedelta(days=AUTOMATIC_AI_LOOKBACK_DAYS)
    states = db.query(SyncStateRecord).filter(
        SyncStateRecord.automatic_ai_enabled.is_(True),
        SyncStateRecord.automatic_ai_generation.isnot(None),
    ).order_by(SyncStateRecord.id.asc()).all()

    remaining = limit
    stale_statuses = ("stale", "legacy_stale", "provenance_unknown")
    unavailable_statuses = ("queued", "running", "failed", "dead_letter", "paused")
    gap_filters = []
    if "triage" in generated:
        gap_filters.append(TicketRecord.ai_reasoning.is_(None))
    if "summary" in generated:
        gap_filters.append(TicketRecord.summary.is_(None))
    if "resolution" in generated:
        gap_filters.append(TicketRecord.recommended_solution.is_(None))
    gap_filters.append(TicketRecord.ai_status.in_(stale_statuses))

    for state in states:
        if remaining <= 0:
            break
        tickets = db.query(TicketRecord).filter(
            TicketRecord.binding_id == state.binding_id,
            TicketRecord.external_source == state.provider,
            or_(
                TicketRecord.external_created_at >= cutoff,
                TicketRecord.external_updated_at >= cutoff,
                TicketRecord.external_conversation_updated_at >= cutoff,
                TicketRecord.created_at >= cutoff,
            ),
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_(unavailable_statuses),
            ),
            or_(*gap_filters),
        ).order_by(
            TicketRecord.external_updated_at.asc(),
            TicketRecord.created_at.asc(),
            TicketRecord.id.asc(),
        ).limit(remaining).all()
        for ticket in tickets:
            artifacts = _missing_automatic_artifacts(ticket, enabled)
            if not artifacts:
                continue
            _queue_analysis(ticket, artifacts)
            result["queued"] += 1
            remaining -= 1
            if remaining <= 0:
                break

    if result["queued"]:
        db.commit()
    return result


def _project_source_status(source_status: str) -> tuple[str, str, str]:
    """Project one provider status into external, workflow, and display state."""
    workflow_status = (
        "Closed"
        if source_status.lower() in ("closed", "resolved")
        else source_status
    )
    return source_status, workflow_status, workflow_status


def _utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).replace("\r\n", "\n").replace(
        "\r", "\n"
    ).replace("\x00", "\ufffd")


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_external_ticket(ext: ExternalTicket) -> ExternalTicket:
    optional_fields = (
        "assignee_id",
        "external_group_id",
        "external_category",
        "external_subcategory",
        "external_item_category",
        "external_priority_code",
        "external_status_code",
        "ticket_type",
        "requester_id",
        "requester_email",
        "external_workspace_id",
    )
    updates = {
        field: (
            _normalize_text(getattr(ext, field))
            if getattr(ext, field) is not None else None
        )
        for field in (
            "external_id",
            "subject",
            "description",
            "reporter",
            "priority",
            "status",
        )
    }
    for field in optional_fields:
        value = getattr(ext, field)
        updates[field] = _normalize_text(value) if value is not None else None
    return ext.model_copy(update=updates)


def _automatic_eligibility(
    state: SyncStateRecord,
    activity_at: Optional[datetime],
) -> tuple[str, bool, str]:
    if state.automatic_ai_generation is None:
        return "historical_seed", False, "automatic_ai_disabled"
    cutoff = _utc_naive(state.automatic_ai_cutover_at)
    activity_at = _utc_naive(activity_at)
    if cutoff is None:
        return "realtime", False, "missing_cutover"
    if activity_at is None:
        return "realtime", False, "missing_authoritative_activity_time"
    if activity_at > datetime.utcnow():
        return "realtime", False, "future_authoritative_activity_time"
    if activity_at < cutoff:
        return "realtime", False, "before_cutover"
    if not state.automatic_ai_enabled:
        return "realtime", False, "automatic_ai_paused"
    return "realtime", True, "at_or_after_cutover"


def enable_automatic_ai(
    db: Session,
    *,
    binding_id: str,
    provider: str,
    actor_id: str,
    reason: str,
    expected_generation: Optional[int] = None,
) -> SyncStateRecord:
    """Create the first audited realtime boundary; never infer one from deploy time."""
    state = db.query(SyncStateRecord).filter(
        SyncStateRecord.binding_id == binding_id,
        SyncStateRecord.provider == provider,
    ).with_for_update().first()
    if state is None:
        state = SyncStateRecord(
            binding_id=binding_id,
            provider=provider,
            last_status="idle",
            automatic_ai_enabled=False,
        )
        db.add(state)
        db.flush()
    current_generation = state.automatic_ai_generation or 0
    if expected_generation is not None and expected_generation != current_generation:
        raise ValueError("automatic_ai_generation_conflict")
    if state.automatic_ai_enabled or state.automatic_ai_cutover_at is not None:
        raise ValueError("automatic_ai_already_enabled")
    now = datetime.utcnow()
    state.automatic_ai_enabled = True
    state.automatic_ai_generation = current_generation + 1
    state.automatic_ai_cutover_at = now
    state.automatic_ai_enabled_at = now
    state.automatic_ai_enabled_by = actor_id
    state.last_error = None
    db.flush()
    return state


def pause_automatic_ai(
    db: Session,
    *,
    binding_id: str,
    provider: str,
    actor_id: str,
    expected_generation: int,
) -> tuple[SyncStateRecord, int]:
    """Stop new eligibility and revoke queued/running work atomically."""
    state = db.query(SyncStateRecord).filter(
        SyncStateRecord.binding_id == binding_id,
        SyncStateRecord.provider == provider,
    ).with_for_update().first()
    if state is None or state.automatic_ai_generation is None:
        raise ValueError("automatic_ai_not_enabled")
    if state.automatic_ai_generation != expected_generation:
        raise ValueError("automatic_ai_generation_conflict")
    if not state.automatic_ai_enabled:
        raise ValueError("automatic_ai_already_paused")
    state.automatic_ai_enabled = False
    state.automatic_ai_paused_at = datetime.utcnow()
    state.automatic_ai_paused_by = actor_id
    revoked = db.query(TicketRecord).filter(
        TicketRecord.binding_id == binding_id,
        TicketRecord.external_source == provider,
        TicketRecord.ai_status.in_(("queued", "running")),
    ).update({
        TicketRecord.ai_status: "paused",
        TicketRecord.ai_claim_id: None,
        TicketRecord.ai_lease_expires_at: None,
        TicketRecord.ai_next_attempt_at: None,
    }, synchronize_session=False)
    db.flush()
    return state, int(revoked or 0)


def _record_activity(
    db: Session,
    *,
    state: SyncStateRecord,
    ticket: TicketRecord,
    entity_type: str,
    external_id: str,
    revision_hash: str,
    activity_at: Optional[datetime],
    artifacts: set[str],
) -> tuple[bool, bool]:
    existing = db.query(ExternalActivityRecord.id).filter(
        ExternalActivityRecord.binding_id == ticket.binding_id,
        ExternalActivityRecord.provider == ticket.external_source,
        ExternalActivityRecord.ticket_id == ticket.id,
        ExternalActivityRecord.entity_type == entity_type,
        ExternalActivityRecord.external_id == external_id,
        ExternalActivityRecord.revision_hash == revision_hash,
    ).first()
    if existing:
        return False, False
    mode, eligible, reason = _automatic_eligibility(state, activity_at)
    if mode == "historical_seed":
        eligible = False
        reason = "historical_seed_not_eligible"
    elif not artifacts and reason == "at_or_after_cutover":
        eligible = False
        reason = "no_public_ai_effect"
    db.add(ExternalActivityRecord(
        binding_id=ticket.binding_id,
        provider=ticket.external_source or "",
        ticket_id=ticket.id,
        entity_type=entity_type,
        external_id=external_id,
        revision_hash=revision_hash,
        activity_at=_utc_naive(activity_at),
        acquisition_mode=mode,
        automatic_ai_generation=(state.automatic_ai_generation if eligible else None),
        automatic_ai_eligible=eligible,
        eligibility_reason=reason,
        affected_artifacts=",".join(sorted(artifacts)) or None,
    ))
    return True, eligible


def _source_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"value_state": "unavailable", "value": None}
    normalized = _normalize_text(value)
    return {
        "value_state": "empty" if normalized == "" else "present",
        "value": normalized,
    }


def _source_context_payload(ext: ExternalTicket) -> dict[str, Any]:
    return {
        "priority_raw": _source_value(ext.external_priority_code),
        "priority_mapped": _source_value(ext.priority),
        "ticket_type_raw": _source_value(ext.ticket_type),
        "ticket_type_mapped": _source_value(
            (ext.ticket_type or "incident").lower()
        ),
        "category": _source_value(ext.external_category),
        "subcategory": _source_value(ext.external_subcategory),
        "item_category": _source_value(ext.external_item_category),
        "group_id": _source_value(ext.external_group_id),
        "responder_id": _source_value(ext.assignee_id),
    }


def _project_ticket_context(
    db: Session,
    ticket: TicketRecord,
    ext: ExternalTicket,
    provider: str,
) -> None:
    context_hash = _canonical_hash(_source_context_payload(ext))
    ticket.external_source_context_hash = context_hash
    record = db.query(ExternalTicketContextRecord).filter(
        ExternalTicketContextRecord.binding_id == ticket.binding_id,
        ExternalTicketContextRecord.provider == provider,
        ExternalTicketContextRecord.provider_ticket_id == ext.external_id,
    ).first()
    values = {
        "ticket_id": ticket.id,
        "status_raw": ext.external_status_code,
        "status_mapped": ext.status,
        "priority_raw": ext.external_priority_code,
        "priority_mapped": ext.priority,
        "ticket_type_raw": ext.ticket_type,
        "ticket_type_mapped": (ext.ticket_type or "incident").lower(),
        "category": ext.external_category,
        "subcategory": ext.external_subcategory,
        "item_category": ext.external_item_category,
        "group_external_id": ext.external_group_id,
        "responder_external_id": ext.assignee_id,
        "requester_external_id": ext.requester_id,
        "workspace_external_id": ext.external_workspace_id,
        "provider_created_at": _utc_naive(ext.created_at),
        "provider_updated_at": _utc_naive(ext.updated_at),
        "provider_resolved_at": _utc_naive(ext.resolved_at),
        "provider_due_at": _utc_naive(ext.due_by),
        "source_context_hash": context_hash,
        "fetched_at": datetime.utcnow(),
    }
    if record is None:
        record = ExternalTicketContextRecord(
            id=str(uuid.uuid4()),
            binding_id=ticket.binding_id,
            provider=provider,
            provider_ticket_id=ext.external_id,
            **values,
        )
        db.add(record)
    else:
        for key, value in values.items():
            setattr(record, key, value)


def _conversation_revision_hash(conversation: ExternalConversation) -> str:
    body = _normalize_text(conversation.body)
    return _canonical_hash({
        "id": conversation.external_id,
        "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "private": conversation.is_private,
        "incoming": conversation.incoming,
        "source": conversation.source,
        "author_id": conversation.author_id,
        "created_at": _utc_naive(conversation.created_at).isoformat()
        if conversation.created_at else None,
        "updated_at": _utc_naive(conversation.updated_at).isoformat()
        if conversation.updated_at else None,
    })


_TRUNCATION_MARKER = "[...TRUNCATED...]"


def _bounded_conversation_body(value: Optional[str]) -> tuple[str, bool]:
    body = _normalize_text(value)
    if len(body) <= 4_000:
        return body, False
    return body[:3_499] + _TRUNCATION_MARKER + body[-484:], True


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _render_public_thread(
    rows: list[ExternalConversationRecord],
    required_ids: Optional[set[str]] = None,
) -> str:
    required_ids = required_ids or set()
    candidates: list[tuple[tuple[datetime, str], dict[str, Any]]] = []
    for row in rows:
        is_current_public = not row.deleted and not row.is_private
        if not is_current_public and not row.public_tombstone:
            continue
        sort_time = (
            row.provider_created_at or row.provider_updated_at or datetime.min
        )
        record: dict[str, Any] = {
            "id": row.external_id,
            "created_at": row.provider_created_at.isoformat()
            if row.provider_created_at else None,
            "updated_at": row.provider_updated_at.isoformat()
            if row.provider_updated_at else None,
            "direction": "incoming" if row.incoming else "outgoing",
            "source": row.source,
            "author_external_id": row.author_external_id,
        }
        if is_current_public:
            record["revision_hash"] = row.revision_hash
            body, truncated = _bounded_conversation_body(row.body)
            record["body"] = {
                "value_state": "empty" if body == "" else "present",
                "text": body,
                "body_truncated": truncated,
            }
        else:
            record["revision_hash"] = _canonical_hash({
                "id": row.external_id,
                "value_state": "removed",
                "created_at": row.provider_created_at.isoformat()
                if row.provider_created_at else None,
                "updated_at": row.provider_updated_at.isoformat()
                if row.provider_updated_at else None,
                "deleted": row.deleted,
                "private": row.is_private,
            })
            record["body"] = {
                "value_state": "removed",
                "text": None,
                "body_truncated": False,
            }
        candidates.append(((sort_time, row.external_id), record))

    candidates.sort(key=lambda item: item[0])
    required = [
        candidate for candidate in candidates
        if candidate[1]["id"] in required_ids
    ]
    if len(required) > 50:
        raise ValueError("public transcript has too many required trigger records")
    selected: list[tuple[tuple[datetime, str], dict[str, Any]]] = list(required)
    total = len(candidates)
    required_payload = {
        "policy": "transcript-public-v1",
        "privacy_policy": "privacy-public-only-v1",
        "total_records": total,
        "selected_records": len(selected),
        "omitted_records": total - len(selected),
        "conversations": [item[1] for item in selected],
    }
    if len(_canonical_json(required_payload).encode("utf-8")) > 12_000:
        raise ValueError("required public transcript triggers exceed the byte budget")
    for candidate in reversed(candidates):
        if candidate[1]["id"] in required_ids:
            continue
        if len(selected) >= 50:
            break
        proposed = sorted([candidate, *selected], key=lambda item: item[0])
        payload = {
            "policy": "transcript-public-v1",
            "privacy_policy": "privacy-public-only-v1",
            "total_records": total,
            "selected_records": len(proposed),
            "omitted_records": total - len(proposed),
            "conversations": [item[1] for item in proposed],
        }
        if len(_canonical_json(payload).encode("utf-8")) > 12_000:
            continue
        selected = proposed
    payload = {
        "policy": "transcript-public-v1",
        "privacy_policy": "privacy-public-only-v1",
        "total_records": total,
        "selected_records": len(selected),
        "omitted_records": total - len(selected),
        "conversations": [item[1] for item in selected],
    }
    rendered = _canonical_json(payload)
    if len(rendered.encode("utf-8")) > 12_000:
        raise ValueError("public transcript metadata exceeds its byte budget")
    return rendered


def _ticket_has_ai_material(db: Session, ticket: TicketRecord) -> bool:
    if any((
        ticket.ai_status,
        ticket.ai_source_hash,
        ticket.ai_reasoning,
        ticket.suggested_response,
        ticket.summary,
        ticket.recommended_solution,
    )):
        return True
    return db.query(AIArtifactRecord.id).filter(
        AIArtifactRecord.ticket_id == ticket.id,
        AIArtifactRecord.active.is_(True),
    ).first() is not None


def _project_conversations(
    db: Session,
    *,
    state: SyncStateRecord,
    ticket: TicketRecord,
    conversations: list[ExternalConversation],
    confirmed_absent_ids: set[str],
) -> set[str]:
    provider = ticket.external_source or ""
    existing_rows = db.query(ExternalConversationRecord).filter(
        ExternalConversationRecord.binding_id == ticket.binding_id,
        ExternalConversationRecord.provider == provider,
        ExternalConversationRecord.provider_ticket_id == ticket.external_id,
    ).all()
    existing_by_id = {row.external_id: row for row in existing_rows}
    eligible_artifacts: set[str] = set()
    public_input_changed = False
    required_transcript_ids: set[str] = set()

    for conversation in conversations:
        revision_hash = _conversation_revision_hash(conversation)
        body = _normalize_text(conversation.body)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        row = existing_by_id.get(conversation.external_id)
        prior_public = bool(row and not row.deleted and not row.is_private)
        current_public = not conversation.is_private
        changed = row is None or row.revision_hash != revision_hash or row.deleted
        if not changed:
            continue
        artifacts = (
            {"triage", "summary", "route", "resolution"}
            if prior_public or current_public else set()
        )
        activity_at = (
            conversation.updated_at or conversation.created_at
            if row is None
            else conversation.updated_at
        )
        _created, eligible = _record_activity(
            db,
            state=state,
            ticket=ticket,
            entity_type="conversation",
            external_id=conversation.external_id,
            revision_hash=revision_hash,
            activity_at=activity_at,
            artifacts=artifacts,
        )
        if artifacts:
            public_input_changed = True
            if eligible:
                eligible_artifacts.update(artifacts)
                required_transcript_ids.add(conversation.external_id)
            elif prior_public and not current_public:
                required_transcript_ids.add(conversation.external_id)
        values = {
            "body": body,
            "body_hash": body_hash,
            "is_private": conversation.is_private,
            "incoming": conversation.incoming,
            "source": conversation.source,
            "author_external_id": conversation.author_id,
            "provider_created_at": _utc_naive(conversation.created_at),
            "provider_updated_at": _utc_naive(conversation.updated_at),
            "deleted": False,
            "public_tombstone": (
                bool((row.public_tombstone if row else False) or prior_public)
                if not current_public else False
            ),
            "revision_hash": revision_hash,
            "received_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        if row is None:
            row = ExternalConversationRecord(
                id=str(uuid.uuid4()),
                binding_id=ticket.binding_id,
                provider=provider,
                ticket_id=ticket.id,
                provider_ticket_id=ticket.external_id or "",
                external_id=conversation.external_id,
                **values,
            )
            db.add(row)
            existing_rows.append(row)
            existing_by_id[row.external_id] = row
        else:
            for key, value in values.items():
                setattr(row, key, value)

        comment = db.query(TicketCommentRecord).filter(
            TicketCommentRecord.ticket_id == ticket.id,
            TicketCommentRecord.external_source == provider,
            TicketCommentRecord.external_id == conversation.external_id,
        ).first()
        if comment is None:
            comment = TicketCommentRecord(
                ticket_id=ticket.id,
                author_id=None,
                external_source=provider,
                external_id=conversation.external_id,
            )
            db.add(comment)
        comment.author_name = (
            f"{provider.title()} user {conversation.author_id}"
            if conversation.author_id else provider.title()
        )
        comment.body = body
        comment.is_private = conversation.is_private
        comment.created_at = _utc_naive(conversation.created_at) or datetime.utcnow()
        comment.external_author_id = conversation.author_id
        comment.external_updated_at = _utc_naive(conversation.updated_at)

    for external_id in confirmed_absent_ids:
        row = existing_by_id.get(external_id)
        if row is None or row.deleted:
            continue
        prior_public = not row.is_private
        row.deleted = True
        row.public_tombstone = prior_public or row.public_tombstone
        row.body = None
        row.body_hash = hashlib.sha256(b"").hexdigest()
        row.updated_at = datetime.utcnow()
        row.revision_hash = _canonical_hash({
            "id": external_id,
            "deleted": True,
            "prior_revision_hash": row.revision_hash,
        })
        artifacts = (
            {"triage", "summary", "route", "resolution"}
            if prior_public else set()
        )
        _record_activity(
            db,
            state=state,
            ticket=ticket,
            entity_type="conversation",
            external_id=external_id,
            revision_hash=row.revision_hash,
            activity_at=None,
            artifacts=artifacts,
        )
        if artifacts:
            # Deletion time is not guessed, so the privacy purge invalidates
            # current AI but cannot automatically enqueue replacement work.
            public_input_changed = True
            required_transcript_ids.add(external_id)
        comment = db.query(TicketCommentRecord).filter(
            TicketCommentRecord.ticket_id == ticket.id,
            TicketCommentRecord.external_source == provider,
            TicketCommentRecord.external_id == external_id,
        ).first()
        if comment:
            comment.body = "[REMOVED]"
            comment.is_private = True
            comment.external_updated_at = None

    db.flush()
    if public_input_changed and _ticket_has_ai_material(db, ticket):
        invalidate_ticket_ai(ticket)
    current_rows = db.query(ExternalConversationRecord).filter(
        ExternalConversationRecord.binding_id == ticket.binding_id,
        ExternalConversationRecord.provider == provider,
        ExternalConversationRecord.provider_ticket_id == ticket.external_id,
    ).all()
    if public_input_changed or ticket.external_conversation_text is None:
        ticket.external_conversation_text = _render_public_thread(
            current_rows,
            required_transcript_ids,
        )
    public_times = [
        row.provider_updated_at or row.provider_created_at
        for row in current_rows
        if not row.deleted and not row.is_private
        and (row.provider_updated_at or row.provider_created_at)
    ]
    ticket.external_conversation_updated_at = max(public_times) if public_times else None
    return eligible_artifacts


def _conversation_snapshot_signature(
    conversations: list[ExternalConversation],
) -> list[tuple[str, str]]:
    return sorted(
        (conversation.external_id, _conversation_revision_hash(conversation))
        for conversation in conversations
    )


def _confirm_absent_conversations(
    db: Session,
    adapter,
    ext: ExternalTicket,
    *,
    binding_id: str,
) -> set[str]:
    if not ext.conversations_loaded:
        return set()
    stored = {
        row.external_id
        for row in db.query(ExternalConversationRecord).filter(
            ExternalConversationRecord.binding_id == binding_id,
            ExternalConversationRecord.provider == adapter.provider_name,
            ExternalConversationRecord.provider_ticket_id == ext.external_id,
            ExternalConversationRecord.deleted.is_(False),
        ).all()
    }
    observed = {conversation.external_id for conversation in ext.conversations}
    missing = stored - observed
    if not missing:
        return set()
    import asyncio

    confirmed = asyncio.run(adapter.fetch_ticket_conversations(ext.external_id))
    if _conversation_snapshot_signature(confirmed) != _conversation_snapshot_signature(
        ext.conversations
    ):
        raise RuntimeError("Freshservice conversation confirmation was not stable")
    ext.conversations = confirmed
    return missing


def _ticket_change_artifacts(
    existing: Optional[TicketRecord], ext: ExternalTicket
) -> set[str]:
    if existing is None:
        return {"triage", "summary", "route", "resolution"}
    artifacts: set[str] = set()
    if existing.subject != ext.subject or existing.description != ext.description:
        artifacts.update({"triage", "summary", "route", "resolution"})
    if (
        existing.priority != ext.priority
        or existing.external_priority_code != ext.external_priority_code
        or existing.external_ticket_type_raw != ext.ticket_type
        or existing.ticket_type != (ext.ticket_type or existing.ticket_type or "incident").lower()
        or existing.external_category != ext.external_category
        or existing.external_subcategory != ext.external_subcategory
        or existing.external_item_category != ext.external_item_category
    ):
        artifacts.update({"route", "resolution"})
    if (
        existing.external_group_id != ext.external_group_id
        or existing.external_assignee_id != ext.assignee_id
    ):
        artifacts.add("route")
    return artifacts


def _ticket_revision_hash(ext: ExternalTicket) -> str:
    return _canonical_hash({
        "id": ext.external_id,
        "subject": _normalize_text(ext.subject),
        "description": _normalize_text(ext.description),
        "status_raw": ext.external_status_code,
        "status_mapped": ext.status,
        "requester_id": ext.requester_id,
        "workspace_id": ext.external_workspace_id,
        "source_context": _source_context_payload(ext),
        "created_at": _utc_naive(ext.created_at).isoformat() if ext.created_at else None,
        "updated_at": _utc_naive(ext.updated_at).isoformat() if ext.updated_at else None,
        "resolved_at": _utc_naive(ext.resolved_at).isoformat()
        if ext.resolved_at else None,
        "due_by": _utc_naive(ext.due_by).isoformat() if ext.due_by else None,
        "fr_due_by": _utc_naive(ext.fr_due_by).isoformat() if ext.fr_due_by else None,
    })


def _upsert_ticket(
    db: Session,
    ext: ExternalTicket,
    provider: str,
    overwrite: bool = False,
    binding_id: str = "legacy",
    commit_changes: bool = True,
) -> tuple[str, Optional[TicketRecord]]:
    """Upsert an external ticket. Returns (action, ticket) where action is
    one of "new" / "updated" / "skipped". Source status is authoritative and
    is always reconciled. When `overwrite` is False, other fields on an
    existing local ticket remain untouched."""
    ext = _normalize_external_ticket(ext)
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
            existing.external_status_code = ext.external_status_code
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
            if commit_changes:
                db.commit()
                db.refresh(existing)
                refresh_ticket_documents_if_indexed(db, existing)
            else:
                db.flush()
            return "updated", existing

        analysis_input_changed = (
            existing.subject != ext.subject or existing.description != ext.description
        )
        resolution_input_changed = (
            existing.priority != ext.priority
            or existing.external_priority_code != ext.external_priority_code
            or existing.external_ticket_type_raw != ext.ticket_type
            or existing.ticket_type
            != (ext.ticket_type or existing.ticket_type or "incident").lower()
            or existing.external_category != ext.external_category
            or existing.external_subcategory != ext.external_subcategory
            or existing.external_item_category != ext.external_item_category
        )
        changed = (
            existing.subject != ext.subject
            or existing.description != ext.description
            or existing.reporter != ext.reporter
            or existing.priority != ext.priority
            or existing.external_priority_code != ext.external_priority_code
            or existing.external_ticket_type_raw != ext.ticket_type
            or source_status_changed
            or existing.external_status_code != ext.external_status_code
            or existing.external_assignee_id != ext.assignee_id
            or existing.external_group_id != ext.external_group_id
            or existing.external_category != ext.external_category
            or existing.external_subcategory != ext.external_subcategory
            or existing.external_item_category != ext.external_item_category
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
        existing.external_priority_code = ext.external_priority_code
        existing.external_status_code = ext.external_status_code
        existing.external_ticket_type_raw = ext.ticket_type
        existing.external_source_context_hash = _canonical_hash(
            _source_context_payload(ext)
        )
        existing.external_status = external_status
        existing.external_assignee_id = ext.assignee_id
        existing.external_group_id = ext.external_group_id
        existing.external_category = ext.external_category
        existing.external_subcategory = ext.external_subcategory
        existing.external_item_category = ext.external_item_category
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
        if commit_changes:
            db.commit()
            db.refresh(existing)
            # Keep already-promoted evidence current for every provider update.
            # The refresh gate only admits the ticket's own document, so comments
            # alone never promote requester-controlled ticket text into shared RAG.
            refresh_ticket_documents_if_indexed(db, existing)
        else:
            db.flush()
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
        external_status_code=ext.external_status_code,
        external_priority_code=ext.external_priority_code,
        external_ticket_type_raw=ext.ticket_type,
        external_source_context_hash=_canonical_hash(_source_context_payload(ext)),
        external_assignee_id=ext.assignee_id,
        external_group_id=ext.external_group_id,
        external_category=ext.external_category,
        external_subcategory=ext.external_subcategory,
        external_item_category=ext.external_item_category,
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
    if commit_changes:
        db.commit()
        db.refresh(new_ticket)
    else:
        db.flush()
    return "new", new_ticket


def _apply_external_ticket(
    db: Session,
    *,
    state: SyncStateRecord,
    ext: ExternalTicket,
    adapter,
    overwrite: bool,
    binding_id: str,
) -> tuple[str, Optional[TicketRecord]]:
    provider = adapter.provider_name
    ext = _normalize_external_ticket(ext)
    before = db.query(TicketRecord).filter(
        TicketRecord.binding_id == binding_id,
        TicketRecord.external_source == provider,
        TicketRecord.external_id == ext.external_id,
    ).first()
    ticket_artifacts = _ticket_change_artifacts(before, ext)
    if before is not None and not overwrite:
        # A status-only/manual reconciliation must not consume the provider
        # revision that a later authoritative overwrite still needs to apply.
        ticket_artifacts = set()
    confirmed_absent = (
        _confirm_absent_conversations(
            db, adapter, ext, binding_id=binding_id
        )
        if provider.strip().lower() == "freshservice"
        else set()
    )
    action, ticket = _upsert_ticket(
        db,
        ext,
        provider,
        overwrite=overwrite,
        binding_id=binding_id,
        commit_changes=False,
    )
    if ticket is None:
        if provider.strip().lower() != "freshservice" or before is None:
            return action, ticket
        ticket = before

    eligible_artifacts: set[str] = set()
    if provider.strip().lower() == "freshservice":
        _project_ticket_context(db, ticket, ext, provider)
        if before is None or overwrite:
            activity_at = ext.created_at if before is None else ext.updated_at
            _created, eligible = _record_activity(
                db,
                state=state,
                ticket=ticket,
                entity_type="ticket",
                external_id=ext.external_id,
                revision_hash=_ticket_revision_hash(ext),
                activity_at=activity_at,
                artifacts=ticket_artifacts,
            )
            if eligible and ticket_artifacts:
                eligible_artifacts.update(ticket_artifacts)
        if ext.conversations_loaded:
            eligible_artifacts.update(_project_conversations(
                db,
                state=state,
                ticket=ticket,
                conversations=ext.conversations,
                confirmed_absent_ids=confirmed_absent,
            ))
        requested = eligible_artifacts & _enabled_analysis_artifacts()
        if requested:
            _queue_analysis(ticket, requested)
    db.commit()
    db.refresh(ticket)
    if action == "updated":
        refresh_ticket_documents_if_indexed(db, ticket)
    return action, ticket


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
                action, ticket = _apply_external_ticket(
                    db,
                    state=sync_state,
                    ext=ext,
                    adapter=adapter,
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
        sync_state = db.query(SyncStateRecord).filter(
            SyncStateRecord.binding_id == binding_id,
            SyncStateRecord.provider == adapter.provider_name,
        ).first()
        if sync_state is None:
            sync_state = SyncStateRecord(
                binding_id=binding_id,
                provider=adapter.provider_name,
                total_synced=0,
                automatic_ai_enabled=False,
            )
            db.add(sync_state)
            db.commit()
            db.refresh(sync_state)
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
                if (
                    existing_state is not None
                    and not overwrite
                    and adapter.provider_name.strip().lower() != "freshservice"
                ):
                    authoritative_state = _project_source_status(ext.status)
                    if existing_state == authoritative_state:
                        result["skipped"] += 1
                        continue
                action, ticket = _apply_external_ticket(
                    db,
                    state=sync_state,
                    ext=ext,
                    adapter=adapter,
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
        import asyncio

        if (
            adapter.provider_name.strip().lower() == "freshservice"
            and hasattr(adapter, "fetch_ticket_raw")
            and hasattr(adapter, "_parse_ticket")
        ):
            raw = asyncio.run(adapter.fetch_ticket_raw(event.external_id))
            ext = adapter._parse_ticket(raw)
            ext.conversations = asyncio.run(
                adapter.fetch_ticket_conversations(event.external_id)
            )
            ext.conversations_loaded = True
        else:
            raw = event.raw.get("ticket", event.raw.get("data", {}))
            ext = ExternalTicket(
                external_id=event.external_id,
                subject=raw.get("subject", ""),
                description=raw.get("description_text", raw.get("description", "")) or "",
                reporter=str(raw.get("requester_id", "")),
                priority=adapter.map_priority(raw.get("priority", 3)),
                status=adapter.map_status(raw.get("status", 2)),
                assignee_id=str(raw.get("responder_id")) if raw.get("responder_id") else None,
                external_group_id=str(raw.get("group_id")) if raw.get("group_id") else None,
                external_category=str(raw.get("category")) if raw.get("category") else None,
                external_subcategory=str(raw.get("sub_category")) if raw.get("sub_category") else None,
                external_item_category=str(raw.get("item_category")) if raw.get("item_category") else None,
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
        state = db.query(SyncStateRecord).filter(
            SyncStateRecord.binding_id == binding_id,
            SyncStateRecord.provider == adapter.provider_name,
        ).first()
        if state is None:
            state = SyncStateRecord(
                binding_id=binding_id,
                provider=adapter.provider_name,
                automatic_ai_enabled=False,
            )
            db.add(state)
            db.commit()
            db.refresh(state)
        _action, ticket = _apply_external_ticket(
            db,
            state=state,
            ext=ext,
            adapter=adapter,
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
