import json
import hashlib
import os
import asyncio
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Collection, List, Optional

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from ..database import (
    AIArtifactRecord,
    ExternalActivityRecord,
    ExternalAttachmentRecord,
    ExternalConversationRecord,
    ExternalGroupMembershipRecord,
    ExternalGroupRecord,
    ExternalTicketContextRecord,
    ExternalUserRecord,
    ProblemTicketLinkRecord,
    SessionLocal,
    SyncStateRecord,
    TicketCommentRecord,
    TicketRecord,
)
from ..ai_contracts import ResolverRoutingAnalysis
from ..schema import ExternalAttachment, ExternalConversation, ExternalTicket, WebhookEvent
from ..portable_keys import portable_ascii_lower
from ..attachment_storage import (
    AzureBlobAttachmentStore,
    attachment_max_bytes,
    attachment_storage_configured,
    safe_blob_name,
)
# Kept as a module attribute for compatibility with integrations/tests that
# patch it. External persistence never promotes un-indexed provider text into
# shared RAG: only tickets that already have evidence documents are refreshed
# when their provider content changes (see refresh_ticket_documents_if_indexed).
from ..ticket_vectors import (
    refresh_ticket_documents_background,
    refresh_ticket_documents_if_indexed,
)
from ..ai_state import (
    automatic_ai_policy_eligible_filter,
    has_terminal_ai_policy_outcome,
    invalidate_ticket_ai,
    invalidate_ticket_resolution,
    invalidate_ticket_routing,
    merge_terminal_ai_policy_errors,
)
from ..ai_eligibility import (
    active_ticket_filter,
    mark_terminal_ai_not_applicable,
    ticket_is_terminal,
)
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


def _queue_analysis(
    db: Session,
    ticket: TicketRecord,
    artifacts: set[str],
) -> None:
    if ticket_is_terminal(db, ticket):
        mark_terminal_ai_not_applicable(ticket)
        return
    if not artifacts:
        return
    already_queued = ticket.ai_status == "queued"
    if already_queued:
        artifacts.update(
            item for item in (ticket.ai_requested_artifacts or "").split(",") if item
        )
    ticket.ai_status = "queued"
    ticket.ai_requested_artifacts = ",".join(sorted(artifacts))
    if not already_queued:
        ticket.ai_next_attempt_at = None
        ticket.ai_error = merge_terminal_ai_policy_errors(ticket.ai_error)


AUTOMATIC_AI_LOOKBACK_DAYS = 28
AUTOMATIC_FETCH_DAYS = 28
BACKGROUND_HISTORY_EPOCH = datetime(1970, 1, 1)
# Provider-owned flow timestamps must cover the default operational reporting
# window, which is intentionally wider than the automatic AI admission lane.
# Keep the two boundaries independent: 28 days controls automatic AI cost,
# while this one-time replay makes the 30-day OPS Tower flow exact.
PROVIDER_TIMESTAMP_REPAIR_DAYS = 30
PROVIDER_TIMESTAMP_REPAIR_VERSION = 2
BACKGROUND_HISTORY_SCAN_VERSION = 1


def active_routing_backlog_enabled() -> bool:
    """Whether this deployment explicitly admits older active tickets.

    The realtime cutover remains the default safety boundary. A deployment
    must opt in before the worker can classify the pre-existing open backlog.
    """
    return (os.getenv("AI_ACTIVE_ROUTING_BACKLOG_ENABLED") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def ticket_created_within_filter(cutoff: datetime):
    """Return the authoritative creation-time predicate for bounded AI work.

    Freshservice creation time wins whenever it is present. Tickety OPS Tower's local
    creation time is only a fallback for records whose provider creation time
    is unavailable; otherwise importing an old provider ticket today would
    incorrectly make it eligible for automatic analysis.
    """
    return or_(
        TicketRecord.external_created_at >= cutoff,
        and_(
            TicketRecord.external_created_at.is_(None),
            TicketRecord.created_at >= cutoff,
        ),
    )


def _ticket_created_within_automatic_window(
    ticket: TicketRecord,
    *,
    now: Optional[datetime] = None,
) -> bool:
    current = _utc_naive(now) or datetime.utcnow()
    created_at = _utc_naive(ticket.external_created_at)
    if created_at is None:
        created_at = _utc_naive(ticket.created_at)
    return bool(
        created_at is not None
        and created_at >= current - timedelta(days=AUTOMATIC_AI_LOOKBACK_DAYS)
        and created_at <= current
    )


def _ticket_has_resolver_route(ticket: TicketRecord) -> bool:
    """Validate the persisted resolver bundle against the authoritative schema."""
    try:
        _resolver_route_payload(ticket)
        return True
    except (TypeError, ValueError):
        return False


def _resolver_route_payload(ticket: TicketRecord) -> dict[str, Any]:
    return ResolverRoutingAnalysis.model_validate({
        "primary_group": ticket.ai_suggested_team,
        "secondary_group": ticket.ai_secondary_team,
        "confidence": ticket.ai_routing_confidence,
        "scope": ticket.ai_routing_scope,
        "affected_service": ticket.ai_affected_service,
        "failure_domain": ticket.ai_failure_domain,
        "reason": ticket.ai_routing_reason,
    }).model_dump()


def _missing_automatic_artifacts(
    ticket: TicketRecord,
    enabled: set[str],
    *,
    route_provenance_current: Optional[bool] = None,
) -> set[str]:
    """Return only durable AI gaps that can be completed by the worker.

    Resolver routing is a persisted LLM artifact and can be enabled or repaired
    independently of general triage.
    """
    generated = enabled & {"triage", "summary", "route", "resolution"}
    generated = {
        artifact for artifact in generated
        if not has_terminal_ai_policy_outcome(ticket, {artifact})
    }
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
    if "route" in generated and (
        stale
        or not _ticket_has_resolver_route(ticket)
        or route_provenance_current is False
    ):
        missing.add("route")
    return missing


def _current_route_artifact_ticket_ids(
    db: Session,
    tickets: Collection[TicketRecord],
    *,
    expected_pipeline_version: Optional[str],
    expected_model: Optional[str],
    allow_synthetic_artifacts: bool = False,
) -> set[str]:
    expected_by_ticket: dict[str, tuple[str, str]] = {}
    for ticket in tickets:
        if not ticket.ai_routing_input_hash:
            continue
        try:
            route_payload = _resolver_route_payload(ticket)
        except (TypeError, ValueError):
            continue
        serialized = json.dumps(
            route_payload,
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        )
        expected_by_ticket[ticket.id] = (
            ticket.ai_routing_input_hash,
            hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        )
    if not expected_by_ticket:
        return set()
    if not expected_pipeline_version or not expected_model:
        return set(expected_by_ticket)
    query = db.query(
        AIArtifactRecord.ticket_id,
        AIArtifactRecord.input_hash,
        AIArtifactRecord.content_hash,
    ).filter(
        AIArtifactRecord.ticket_id.in_(expected_by_ticket),
        AIArtifactRecord.artifact == "route",
        AIArtifactRecord.pipeline_version == expected_pipeline_version,
        AIArtifactRecord.model == expected_model,
        AIArtifactRecord.active.is_(True),
    )
    if not allow_synthetic_artifacts:
        query = query.filter(AIArtifactRecord.synthetic.is_(False))
    return {
        ticket_id
        for ticket_id, input_hash, content_hash in query.all()
        if expected_by_ticket.get(ticket_id) == (input_hash, content_hash)
    }


def _route_artifact_gap_filter(
    db: Session,
    *,
    expected_pipeline_version: Optional[str],
    expected_model: Optional[str],
    allow_synthetic_artifacts: bool = False,
):
    if not expected_pipeline_version or not expected_model:
        return None
    query = db.query(AIArtifactRecord.id).filter(
        AIArtifactRecord.ticket_id == TicketRecord.id,
        AIArtifactRecord.artifact == "route",
        AIArtifactRecord.pipeline_version == expected_pipeline_version,
        AIArtifactRecord.model == expected_model,
        AIArtifactRecord.input_hash == TicketRecord.ai_routing_input_hash,
        AIArtifactRecord.active.is_(True),
    )
    if not allow_synthetic_artifacts:
        query = query.filter(AIArtifactRecord.synthetic.is_(False))
    return ~query.exists()


def _staged_automatic_artifacts(
    ticket: TicketRecord,
    eligible: set[str],
) -> set[str]:
    """Admit every missing eligible stage as one durable ticket pipeline."""
    enabled = _enabled_analysis_artifacts()
    requested = eligible & enabled
    requested = {
        artifact for artifact in requested
        if not has_terminal_ai_policy_outcome(ticket, {artifact})
    }
    if not requested:
        return set()
    stale = (ticket.ai_status or "").strip().lower() in {
        "stale", "legacy_stale", "provenance_unknown",
    }
    if "triage" in requested and (stale or not ticket.ai_reasoning):
        stage = {"triage"}
    else:
        stage = set()
    if "summary" in requested and (stale or not ticket.summary):
        stage.add("summary")
    if "resolution" in requested and (stale or not ticket.recommended_solution):
        stage.add("resolution")
    if "route" in requested and (stale or not _ticket_has_resolver_route(ticket)):
        stage.add("route")
    return stage


def queue_recent_automatic_ai(
    db: Session,
    *,
    now: Optional[datetime] = None,
    batch_size: int = 5,
    expected_pipeline_version: Optional[str] = None,
    expected_model: Optional[str] = None,
    allow_synthetic_artifacts: bool = False,
) -> dict[str, int]:
    """Queue missing AI work for external tickets created in the last 4 weeks.

    The integration's explicit automatic-AI switch remains the authorization
    boundary. This rolling, bounded scanner is deliberately separate from the
    immutable realtime cutover so existing activity evidence is not rewritten.
    Repeated calls are idempotent because queued/running/terminal rows are not
    selected and completed artifacts are detected before enqueueing.
    """
    enabled = _enabled_analysis_artifacts()
    generated = enabled & {"triage", "summary", "route", "resolution"}
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
    # Keep each persisted gap paired with that artifact's terminal-policy
    # eligibility. A global "at least one artifact is eligible" predicate is
    # too broad: a ticket with a terminal summary outcome and a deliberately
    # empty summary would otherwise match forever even when every other
    # artifact is current. Because the query is newest-first and bounded,
    # enough such false positives can permanently starve real older gaps.
    gap_filters = []
    stale_gap = TicketRecord.ai_status.in_(stale_statuses)
    if "triage" in generated:
        gap_filters.append(and_(
            automatic_ai_policy_eligible_filter({"triage"}),
            or_(stale_gap, TicketRecord.ai_reasoning.is_(None)),
        ))
    if "route" in generated:
        route_gaps = [
            stale_gap,
            TicketRecord.ai_suggested_team.is_(None),
            TicketRecord.ai_routing_confidence.is_(None),
            TicketRecord.ai_routing_scope.is_(None),
            TicketRecord.ai_affected_service.is_(None),
            TicketRecord.ai_failure_domain.is_(None),
            TicketRecord.ai_routing_reason.is_(None),
            TicketRecord.ai_routing_input_hash.is_(None),
        ]
        provenance_gap = _route_artifact_gap_filter(
            db,
            expected_pipeline_version=expected_pipeline_version,
            expected_model=expected_model,
            allow_synthetic_artifacts=allow_synthetic_artifacts,
        )
        if provenance_gap is not None:
            route_gaps.append(provenance_gap)
        gap_filters.append(and_(
            automatic_ai_policy_eligible_filter({"route"}),
            or_(*route_gaps),
        ))
    if "summary" in generated:
        gap_filters.append(and_(
            automatic_ai_policy_eligible_filter({"summary"}),
            or_(stale_gap, TicketRecord.summary.is_(None)),
        ))
    if "resolution" in generated:
        gap_filters.append(and_(
            automatic_ai_policy_eligible_filter({"resolution"}),
            or_(stale_gap, TicketRecord.recommended_solution.is_(None)),
        ))

    for state in states:
        if remaining <= 0:
            break
        tickets = db.query(TicketRecord).filter(
            TicketRecord.binding_id == state.binding_id,
            TicketRecord.external_source == state.provider,
            active_ticket_filter(db),
            ticket_created_within_filter(cutoff),
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_(unavailable_statuses),
            ),
            or_(*gap_filters),
        ).order_by(
            TicketRecord.external_created_at.desc().nullslast(),
            TicketRecord.created_at.desc().nullslast(),
            TicketRecord.external_updated_at.desc().nullslast(),
            TicketRecord.id.asc(),
        ).limit(remaining).all()
        current_route_ticket_ids = (
            _current_route_artifact_ticket_ids(
                db,
                tickets,
                expected_pipeline_version=expected_pipeline_version,
                expected_model=expected_model,
                allow_synthetic_artifacts=allow_synthetic_artifacts,
            )
            if "route" in generated
            else set()
        )
        for ticket in tickets:
            artifacts = _missing_automatic_artifacts(
                ticket,
                enabled,
                route_provenance_current=(
                    ticket.id in current_route_ticket_ids
                    if "route" in generated
                    else None
                ),
            )
            if not artifacts:
                continue
            _queue_analysis(db, ticket, artifacts)
            result["queued"] += 1
            remaining -= 1
            if remaining <= 0:
                break

    if result["queued"]:
        db.commit()
    return result


def queue_active_routing_backlog(
    db: Session,
    *,
    batch_size: int = 5,
    expected_pipeline_version: Optional[str] = None,
    expected_model: Optional[str] = None,
    allow_synthetic_artifacts: bool = False,
) -> dict[str, int | bool]:
    """Queue resolver routing for active external tickets outside lookback.

    This bounded repair lane is disabled unless the deployment explicitly
    opts in. It requires automatic routing, only considers active tickets under
    an enabled binding, and never queues summaries or resolution plans.
    General triage accompanies routing only when enabled and missing. Repeated
    sweeps are idempotent.
    """
    enabled = _enabled_analysis_artifacts()
    result: dict[str, int | bool] = {
        "enabled": active_routing_backlog_enabled(),
        "queued": 0,
    }
    if not result["enabled"] or "route" not in enabled:
        return result

    limit = max(1, min(int(batch_size), 25))
    states = db.query(SyncStateRecord).filter(
        SyncStateRecord.automatic_ai_enabled.is_(True),
        SyncStateRecord.automatic_ai_generation.isnot(None),
    ).order_by(SyncStateRecord.id.asc()).all()
    remaining = limit
    unavailable_statuses = ("queued", "running", "failed", "dead_letter", "paused")
    stale_statuses = ("stale", "legacy_stale", "provenance_unknown")
    provenance_gap = _route_artifact_gap_filter(
        db,
        expected_pipeline_version=expected_pipeline_version,
        expected_model=expected_model,
        allow_synthetic_artifacts=allow_synthetic_artifacts,
    )

    for state in states:
        if remaining <= 0:
            break
        tickets = db.query(TicketRecord).filter(
            TicketRecord.binding_id == state.binding_id,
            TicketRecord.external_source == state.provider,
            active_ticket_filter(db),
            automatic_ai_policy_eligible_filter({"route"}),
            or_(
                TicketRecord.ai_status.is_(None),
                TicketRecord.ai_status.notin_(unavailable_statuses),
            ),
            or_(
                TicketRecord.ai_suggested_team.is_(None),
                TicketRecord.ai_routing_confidence.is_(None),
                TicketRecord.ai_routing_scope.is_(None),
                TicketRecord.ai_affected_service.is_(None),
                TicketRecord.ai_failure_domain.is_(None),
                TicketRecord.ai_routing_reason.is_(None),
                TicketRecord.ai_routing_input_hash.is_(None),
                TicketRecord.ai_status.in_(stale_statuses),
                *([provenance_gap] if provenance_gap is not None else []),
            ),
        ).order_by(
            # Recovery work must not be starved by a continuously replenished
            # stream of newer, never-analyzed tickets. Explicit stale states
            # are bounded repair signals and therefore lead each sweep.
            case(
                (TicketRecord.ai_status.in_(stale_statuses), 0),
                else_=1,
            ).asc(),
            TicketRecord.external_updated_at.desc().nullslast(),
            TicketRecord.updated_at.desc().nullslast(),
            TicketRecord.id.asc(),
        ).limit(remaining).all()
        for ticket in tickets:
            artifacts = {"route"}
            if "triage" in enabled and not ticket.ai_reasoning:
                artifacts.add("triage")
            _queue_analysis(db, ticket, artifacts)
            result["queued"] = int(result["queued"]) + 1
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
        if portable_ascii_lower(source_status) in ("closed", "resolved")
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
        "requester_name",
        "requester_email",
        "requester_title",
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
    if ext.description_html is not None:
        updates["description_html"] = _normalize_text(ext.description_html)
    return ext.model_copy(update=updates)


def _upsert_embedded_external_user(
    db: Session,
    *,
    binding_id: str,
    provider: str,
    external_id: Optional[str],
    user_type: str,
    name: Optional[str],
    email: Optional[str],
    title: Optional[str] = None,
    records_by_identity: Optional[
        dict[tuple[str, str], ExternalUserRecord]
    ] = None,
) -> None:
    """Cache identity already authorized in a ticket/conversation envelope.

    Freshservice can allow ticket reads while denying account-wide directory
    endpoints. Keeping the embedded projection makes identity enrichment
    reliable without broadening provider permissions.
    """
    external_id = _normalize_text(external_id).strip() if external_id else ""
    name = _normalize_text(name).strip() if name else ""
    email = _normalize_text(email).strip().lower() if email else ""
    title = _normalize_text(title).strip() if title else ""
    if not external_id or user_type not in {"agent", "requester"}:
        return
    # Production sessions intentionally disable autoflush.  A single ticket
    # can contain several conversations from the same author, so reuse an
    # identity already staged in this transaction before querying persisted
    # rows.  Otherwise each conversation stages a duplicate record and the
    # commit fails the external-user identity constraint.
    identity = (user_type, external_id)
    record = (
        records_by_identity.get(identity)
        if records_by_identity is not None else None
    )
    if record is None and records_by_identity is None:
        record = next((
            pending for pending in db.new
            if isinstance(pending, ExternalUserRecord)
            and pending.binding_id == binding_id
            and pending.provider == provider
            and pending.user_type == user_type
            and pending.external_id == external_id
        ), None)
    if record is None and records_by_identity is None:
        record = db.query(ExternalUserRecord).filter(
            ExternalUserRecord.binding_id == binding_id,
            ExternalUserRecord.provider == provider,
            ExternalUserRecord.user_type == user_type,
            ExternalUserRecord.external_id == external_id,
        ).first()
    now = datetime.utcnow()
    if record is None:
        record = ExternalUserRecord(
            id=str(uuid.uuid4()),
            binding_id=binding_id,
            provider=provider,
            external_id=external_id,
            user_type=user_type,
            name=name or email or f"{provider.title()} {user_type}",
            email=email or None,
            title=title or None,
            active=True,
            profile_json='{"source":"embedded_ticket_projection"}',
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        if records_by_identity is not None:
            records_by_identity[identity] = record
        return
    if name and _embedded_identity_name_quality(
        name, provider=provider, user_type=user_type
    ) >= _embedded_identity_name_quality(
        record.name, provider=provider, user_type=user_type
    ):
        record.name = name
    if email and _embedded_identity_email_quality(email) >= (
        _embedded_identity_email_quality(record.email)
    ):
        record.email = email
    if title:
        record.title = title
    record.active = True
    record.fetched_at = now
    record.updated_at = now


_GENERIC_EMBEDDED_IDENTITY_TERMS = (
    "freshservice",
    "helpdesk",
    "service desk",
    "support",
    "external user",
)


def _embedded_identity_name_quality(
    value: Optional[str], *, provider: str, user_type: str
) -> int:
    """Rank provider-authored names so placeholders cannot erase people."""
    normalized = " ".join(str(value or "").split()).casefold()
    if not normalized:
        return 0
    exact_placeholders = {
        user_type.casefold(),
        f"{provider} {user_type}".casefold(),
        f"external {user_type}".casefold(),
    }
    if normalized in exact_placeholders or any(
        term in normalized for term in _GENERIC_EMBEDDED_IDENTITY_TERMS
    ):
        return 1
    if "@" in normalized and " " not in normalized:
        return 1
    return 3 if len(normalized.split()) >= 2 else 2


def _embedded_identity_email_quality(value: Optional[str]) -> int:
    normalized = str(value or "").strip().casefold()
    if not normalized or "@" not in normalized:
        return 0
    local = normalized.split("@", 1)[0].replace(".", " ").replace("_", " ")
    return 1 if any(
        term in local for term in ("helpdesk", "support", "service desk")
    ) else 2


def reconcile_embedded_agent_identities(db: Session) -> int:
    """Repair placeholder agent profiles from same-ID outgoing evidence.

    Only provider-authored outgoing conversation records with the exact same
    binding, provider, and external agent ID are considered. Requester rows,
    email similarity, and names from any other identity are deliberately
    excluded, so this improves display quality without linking people by
    inference.
    """
    agents = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
    ).all()
    repairable = [
        agent for agent in agents
        if _embedded_identity_name_quality(
            agent.name, provider=agent.provider, user_type="agent"
        ) < 3
        or _embedded_identity_email_quality(agent.email) < 2
    ]
    if not repairable:
        return 0
    identity_filters = [and_(
        ExternalConversationRecord.binding_id == agent.binding_id,
        ExternalConversationRecord.provider == agent.provider,
        ExternalConversationRecord.author_external_id == agent.external_id,
    ) for agent in repairable]
    evidence = db.query(
        ExternalConversationRecord.binding_id,
        ExternalConversationRecord.provider,
        ExternalConversationRecord.author_external_id,
        ExternalConversationRecord.author_name,
        ExternalConversationRecord.author_email,
        func.count(ExternalConversationRecord.id).label("evidence_count"),
    ).filter(
        ExternalConversationRecord.incoming.is_(False),
        ExternalConversationRecord.deleted.is_(False),
        or_(*identity_filters),
    ).group_by(
        ExternalConversationRecord.binding_id,
        ExternalConversationRecord.provider,
        ExternalConversationRecord.author_external_id,
        ExternalConversationRecord.author_name,
        ExternalConversationRecord.author_email,
    ).all()
    by_identity: dict[tuple[str, str, str], list[Any]] = {}
    for row in evidence:
        by_identity.setdefault((row[0], row[1], row[2]), []).append(row)

    repaired = 0
    now = datetime.utcnow()
    for agent in repairable:
        candidates = by_identity.get(
            (agent.binding_id, agent.provider, agent.external_id), []
        )
        if not candidates:
            continue
        best_name = max(candidates, key=lambda row: (
            _embedded_identity_name_quality(
                row.author_name, provider=agent.provider, user_type="agent"
            ),
            int(row.evidence_count or 0),
            str(row.author_name or "").casefold(),
        ))
        best_email = max(candidates, key=lambda row: (
            _embedded_identity_email_quality(row.author_email),
            int(row.evidence_count or 0),
            str(row.author_email or "").casefold(),
        ))
        changed = False
        if _embedded_identity_name_quality(
            best_name.author_name, provider=agent.provider, user_type="agent"
        ) > _embedded_identity_name_quality(
            agent.name, provider=agent.provider, user_type="agent"
        ):
            agent.name = " ".join(str(best_name.author_name).split())
            changed = True
        if _embedded_identity_email_quality(
            best_email.author_email
        ) > _embedded_identity_email_quality(agent.email):
            agent.email = str(best_email.author_email).strip().casefold()
            changed = True
        if changed:
            agent.updated_at = now
            repaired += 1
    db.flush()
    return repaired


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
    """Create or resume an explicit automatic-AI boundary.

    The first enable establishes the immutable activity cutover. A later
    resume advances the generation while preserving that cutover, so pausing
    cannot silently redefine which provider activity is eligible.
    """
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
    if state.automatic_ai_enabled:
        raise ValueError("automatic_ai_already_enabled")
    now = datetime.utcnow()
    state.automatic_ai_enabled = True
    state.automatic_ai_generation = current_generation + 1
    if state.automatic_ai_cutover_at is None:
        state.automatic_ai_cutover_at = now
    state.automatic_ai_enabled_at = now
    state.automatic_ai_enabled_by = actor_id
    state.automatic_ai_paused_at = None
    state.automatic_ai_paused_by = None
    state.last_error = None
    # Pausing revokes claimed work with an explicit ``paused`` lifecycle.
    # Make those rows discoverable again on resume; the bounded recent scanner
    # still decides which tickets enter the automatic four-week lane.
    db.query(TicketRecord).filter(
        TicketRecord.binding_id == binding_id,
        TicketRecord.external_source == provider,
        TicketRecord.ai_status == "paused",
    ).update({TicketRecord.ai_status: "stale"}, synchronize_session=False)
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
    existing_revisions: Optional[set[tuple[str, str]]] = None,
) -> tuple[bool, bool]:
    revision_key = (external_id, revision_hash)
    if existing_revisions is not None:
        existing = revision_key in existing_revisions
    else:
        existing = db.query(ExternalActivityRecord.id).filter(
            ExternalActivityRecord.binding_id == ticket.binding_id,
            ExternalActivityRecord.provider == ticket.external_source,
            ExternalActivityRecord.ticket_id == ticket.id,
            ExternalActivityRecord.entity_type == entity_type,
            ExternalActivityRecord.external_id == external_id,
            ExternalActivityRecord.revision_hash == revision_hash,
        ).first() is not None
    if existing:
        return False, False
    mode, eligible, reason = _automatic_eligibility(state, activity_at)
    if mode == "historical_seed":
        eligible = False
        reason = "historical_seed_not_eligible"
    elif not artifacts and reason == "at_or_after_cutover":
        eligible = False
        reason = "no_public_ai_effect"
    elif eligible and not _ticket_created_within_automatic_window(ticket):
        eligible = False
        reason = "ticket_created_before_lookback"
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
    if existing_revisions is not None:
        existing_revisions.add(revision_key)
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
            portable_ascii_lower(ext.ticket_type or "incident")
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
        "ticket_type_mapped": portable_ascii_lower(ext.ticket_type or "incident"),
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
    body_html = _normalize_text(conversation.body_html)
    return _canonical_hash({
        "id": conversation.external_id,
        "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "body_html_hash": hashlib.sha256(body_html.encode("utf-8")).hexdigest(),
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
    relevant_external_ids = {
        conversation.external_id for conversation in conversations
    } | confirmed_absent_ids
    existing_comments = db.query(TicketCommentRecord).filter(
        TicketCommentRecord.ticket_id == ticket.id,
        TicketCommentRecord.external_source == provider,
        TicketCommentRecord.external_id.in_(relevant_external_ids),
    ).all() if relevant_external_ids else []
    comments_by_external_id = {
        row.external_id: row for row in existing_comments
    }
    activity_revisions = set(db.query(
        ExternalActivityRecord.external_id,
        ExternalActivityRecord.revision_hash,
    ).filter(
        ExternalActivityRecord.binding_id == ticket.binding_id,
        ExternalActivityRecord.provider == provider,
        ExternalActivityRecord.ticket_id == ticket.id,
        ExternalActivityRecord.entity_type == "conversation",
        ExternalActivityRecord.external_id.in_(relevant_external_ids),
    ).all()) if relevant_external_ids else set()
    author_ids = {
        _normalize_text(conversation.author_id).strip()
        for conversation in conversations
        if conversation.author_id
    }
    embedded_users_by_identity = {
        (row.user_type, row.external_id): row
        for row in db.new
        if isinstance(row, ExternalUserRecord)
        and row.binding_id == ticket.binding_id
        and row.provider == provider
        and row.external_id in author_ids
    }
    if author_ids:
        for row in db.query(ExternalUserRecord).filter(
            ExternalUserRecord.binding_id == ticket.binding_id,
            ExternalUserRecord.provider == provider,
            ExternalUserRecord.external_id.in_(author_ids),
        ).all():
            embedded_users_by_identity.setdefault(
                (row.user_type, row.external_id), row
            )
    eligible_artifacts: set[str] = set()
    public_input_changed = False
    required_transcript_ids: set[str] = set()

    for conversation in conversations:
        revision_hash = _conversation_revision_hash(conversation)
        body = _normalize_text(conversation.body)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        row = existing_by_id.get(conversation.external_id)
        author_type = "requester" if conversation.incoming else "agent"
        author_name = conversation.author_name
        author_email = conversation.author_email
        if conversation.incoming and (
            not conversation.author_id
            or conversation.author_id == ticket.external_requester_id
        ):
            author_name = ticket.external_requester_name or author_name
            author_email = ticket.external_requester_email or author_email
        author_name = (
            (author_name or "").strip()
            or (author_email or "").strip()
            or f"{provider.title()} {author_type}"
        )
        author_email = (author_email or "").strip().lower() or None
        _upsert_embedded_external_user(
            db,
            binding_id=ticket.binding_id,
            provider=provider,
            external_id=conversation.author_id,
            user_type=author_type,
            name=author_name,
            email=author_email,
            records_by_identity=embedded_users_by_identity,
        )
        prior_public = bool(row and not row.deleted and not row.is_private)
        current_public = not conversation.is_private
        changed = row is None or row.revision_hash != revision_hash or row.deleted
        comment = comments_by_external_id.get(conversation.external_id)
        if not changed:
            row.author_name = author_name
            row.author_email = author_email
            row.received_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            if comment is not None:
                comment.author_name = author_name
                comment.author_email = author_email
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
            existing_revisions=activity_revisions,
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
            "body_html": (
                _normalize_text(conversation.body_html)
                if conversation.body_html is not None else None
            ),
            "body_hash": body_hash,
            "is_private": conversation.is_private,
            "incoming": conversation.incoming,
            "source": conversation.source,
            "author_external_id": conversation.author_id,
            "author_name": author_name,
            "author_email": author_email,
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

        if comment is None:
            comment = TicketCommentRecord(
                ticket_id=ticket.id,
                author_id=None,
                external_source=provider,
                external_id=conversation.external_id,
            )
            db.add(comment)
            comments_by_external_id[conversation.external_id] = comment
        comment.author_name = author_name
        comment.author_email = author_email
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
            existing_revisions=activity_revisions,
        )
        if artifacts:
            # Deletion time is not guessed, so the privacy purge invalidates
            # current AI but cannot automatically enqueue replacement work.
            public_input_changed = True
            required_transcript_ids.add(external_id)
        comment = comments_by_external_id.get(external_id)
        if comment:
            comment.body = "[REMOVED]"
            comment.is_private = True
            comment.external_updated_at = None

    db.flush()
    if public_input_changed and _ticket_has_ai_material(db, ticket):
        invalidate_ticket_ai(ticket)
    if public_input_changed or ticket.external_conversation_text is None:
        ticket.external_conversation_text = _render_public_thread(
            existing_rows,
            required_transcript_ids,
        )
    public_times = [
        row.provider_updated_at or row.provider_created_at
        for row in existing_rows
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
        existing.external_category != ext.external_category
        or existing.external_subcategory != ext.external_subcategory
        or existing.external_item_category != ext.external_item_category
    ):
        artifacts.add("route")
    if (
        existing.priority != ext.priority
        or existing.external_priority_code != ext.external_priority_code
        or existing.external_ticket_type_raw != ext.ticket_type
        or portable_ascii_lower(existing.ticket_type)
        != portable_ascii_lower(ext.ticket_type or existing.ticket_type or "incident")
        or existing.external_category != ext.external_category
        or existing.external_subcategory != ext.external_subcategory
        or existing.external_item_category != ext.external_item_category
    ):
        artifacts.add("resolution")
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
    source_is_resolved = portable_ascii_lower(ext.status) in {
        "closed", "resolved",
    }
    authoritative_resolved_at = ext.resolved_at if source_is_resolved else None

    if existing:
        matched = db.query(TicketRecord).filter(
            TicketRecord.id == existing.id
        ).update(
            {TicketRecord.updated_at: TicketRecord.updated_at},
            synchronize_session=False,
        )
        if matched != 1:
            if commit_changes:
                db.rollback()
            raise RuntimeError("Provider ticket disappeared while synchronization was locking it")
        locked_row = db.query(
            TicketRecord,
            ProblemTicketLinkRecord.id,
        ).outerjoin(
            ProblemTicketLinkRecord,
            ProblemTicketLinkRecord.ticket_id == TicketRecord.id,
        ).filter(
            TicketRecord.id == existing.id
        ).populate_existing().first()
        if locked_row is None:
            if commit_changes:
                db.rollback()
            raise RuntimeError("Provider ticket disappeared while synchronization was locking it")
        existing, linked_problem_id = locked_row
        projected_ticket_type = portable_ascii_lower(
            ext.ticket_type or existing.ticket_type or "incident"
        )
        if (
            projected_ticket_type != "incident"
            and linked_problem_id is not None
        ):
            if commit_changes:
                db.rollback()
            raise RuntimeError(
                "Provider ticket type conflicts with a linked problem; unlink it before synchronization"
            )
        source_status_changed = (
            existing.external_status,
            existing.workflow_status,
            existing.status,
        ) != authoritative_status
        resolution_projection_changed = (
            existing.external_resolved_at != ext.resolved_at
            or existing.resolved_at != authoritative_resolved_at
        )
        if not overwrite:
            if not source_status_changed and not resolution_projection_changed:
                if commit_changes:
                    db.commit()
                return "skipped", None
            existing.external_status = external_status
            existing.external_status_code = ext.external_status_code
            existing.workflow_status = workflow_status
            existing.status = display_status
            if ext.updated_at is not None:
                existing.external_updated_at = ext.updated_at
            existing.external_resolved_at = ext.resolved_at
            existing.updated_at = datetime.utcnow()
            # Provider state owns both closure and its timestamp. Never turn
            # projection/import time into a fabricated resolution event when
            # the provider omitted stats; a later stats-bearing sync repairs it.
            existing.resolved_at = authoritative_resolved_at
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
        routing_input_changed = (
            existing.external_category != ext.external_category
            or existing.external_subcategory != ext.external_subcategory
            or existing.external_item_category != ext.external_item_category
        )
        resolution_input_changed = (
            existing.priority != ext.priority
            or existing.external_priority_code != ext.external_priority_code
            or existing.external_ticket_type_raw != ext.ticket_type
            or portable_ascii_lower(existing.ticket_type) != projected_ticket_type
            or existing.external_category != ext.external_category
            or existing.external_subcategory != ext.external_subcategory
            or existing.external_item_category != ext.external_item_category
        )
        changed = (
            existing.subject != ext.subject
            or existing.description != ext.description
            or existing.external_description_html != ext.description_html
            or existing.reporter != ext.reporter
            or existing.priority != ext.priority
            or existing.external_priority_code != ext.external_priority_code
            or existing.external_ticket_type_raw != ext.ticket_type
            or source_status_changed
            or existing.external_status_code != ext.external_status_code
            or existing.external_assignee_id != ext.assignee_id
            or existing.external_requester_id != ext.requester_id
            or existing.external_requester_name != ext.requester_name
            or existing.external_requester_email != ext.requester_email
            or existing.external_requester_title != ext.requester_title
            or existing.external_group_id != ext.external_group_id
            or existing.external_category != ext.external_category
            or existing.external_subcategory != ext.external_subcategory
            or existing.external_item_category != ext.external_item_category
            or existing.external_workspace_id != ext.external_workspace_id
            or existing.external_updated_at != ext.updated_at
            or existing.external_created_at != ext.created_at
            or resolution_projection_changed
            or existing.external_due_by != ext.due_by
            or existing.external_fr_due_by != ext.fr_due_by
            or portable_ascii_lower(existing.ticket_type) != projected_ticket_type
            or (ext.url and existing.external_url != ext.url)
        )
        if not changed:
            # Nothing to write — count as skipped so the worker doesn't
            # report spurious "updated" activity on every poll.
            if commit_changes:
                db.commit()
            return "skipped", existing
        existing.subject = ext.subject
        existing.description = ext.description
        existing.external_description_html = ext.description_html
        if analysis_input_changed:
            invalidate_ticket_ai(existing)
        elif routing_input_changed:
            invalidate_ticket_routing(existing)
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
        existing.external_requester_id = ext.requester_id
        existing.external_requester_name = ext.requester_name
        existing.external_requester_email = ext.requester_email
        existing.external_requester_title = ext.requester_title
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
        existing.ticket_type = projected_ticket_type
        # These local columns are the query-optimized projection of provider
        # deadlines. Mirror explicit NULL removals instead of retaining stale
        # SLA targets that reports would continue to count as breaches.
        existing.due_by = ext.due_by
        existing.resolution_due_at = ext.due_by
        existing.response_due_at = ext.fr_due_by
        existing.updated_at = datetime.utcnow()
        if source_is_resolved:
            existing.status = display_status
            existing.resolved_at = authoritative_resolved_at
        else:
            existing.status = display_status
            existing.resolved_at = None
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
        external_description_html=ext.description_html,
        reporter=ext.reporter,
        status=workflow_status,
        workflow_status=workflow_status,
        priority=ext.priority,
        ticket_type=portable_ascii_lower(ext.ticket_type or "incident"),
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
        external_requester_id=ext.requester_id,
        external_requester_name=ext.requester_name,
        external_requester_email=ext.requester_email,
        external_requester_title=ext.requester_title,
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
        resolved_at=ext.resolved_at if source_is_resolved else None,
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
    commit_checkpoint: Optional[Callable[[], None]] = None,
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
        _upsert_embedded_external_user(
            db,
            binding_id=binding_id,
            provider=provider,
            external_id=ext.requester_id,
            user_type="requester",
            name=ext.requester_name,
            email=ext.requester_email,
            title=ext.requester_title,
        )
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
        if ticket_is_terminal(db, ticket):
            mark_terminal_ai_not_applicable(ticket)
        else:
            requested = _staged_automatic_artifacts(ticket, eligible_artifacts)
            if requested:
                _queue_analysis(db, ticket, requested)
    if commit_checkpoint is None:
        db.commit()
    else:
        # The checkpoint must verify ownership and commit in one operation.
        # If ownership was replaced, its rollback discards every projection
        # staged above before any stale worker row becomes durable.
        commit_checkpoint()
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


def _bounded_sync_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def freshservice_sync_limits() -> dict[str, int]:
    """Return conservative per-sweep provider work admission limits."""
    return {
        "recent_pages": _bounded_sync_setting(
            "FRESHSERVICE_RECENT_PAGES_PER_SYNC", 2, 1, 10
        ),
        "history_pages": _bounded_sync_setting(
            "FRESHSERVICE_HISTORY_PAGES_PER_SYNC", 1, 1, 5
        ),
        "conversations": _bounded_sync_setting(
            "FRESHSERVICE_CONVERSATIONS_PER_SYNC", 1, 0, 5
        ),
        "attachments": _bounded_sync_setting(
            "FRESHSERVICE_ATTACHMENTS_PER_SYNC", 2, 0, 20
        ),
        "lease_seconds": _bounded_sync_setting(
            "FRESHSERVICE_SYNC_LEASE_SECONDS", 900, 120, 3600
        ),
    }


def _find_sync_state(db: Session, adapter, binding_id: str) -> Optional[SyncStateRecord]:
    return db.query(SyncStateRecord).filter(
        SyncStateRecord.binding_id == binding_id,
        SyncStateRecord.provider == adapter.provider_name,
    ).first()


def _ensure_sync_state(db: Session, adapter, binding_id: str) -> SyncStateRecord:
    state = _find_sync_state(db, adapter, binding_id)
    if state is not None:
        return state
    state = SyncStateRecord(
        binding_id=binding_id,
        provider=adapter.provider_name,
        last_status="idle",
        total_synced=0,
    )
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def _claim_freshservice_run(
    db: Session,
    state: SyncStateRecord,
    *,
    lease_seconds: int,
) -> Optional[str]:
    now = datetime.utcnow()
    if state.next_retry_at and state.next_retry_at > now:
        return None
    token = str(uuid.uuid4())
    stale_before = now - timedelta(seconds=lease_seconds)
    claimed = db.query(SyncStateRecord).filter(
        SyncStateRecord.id == state.id,
        or_(
            SyncStateRecord.run_token.is_(None),
            SyncStateRecord.run_started_at.is_(None),
            SyncStateRecord.run_started_at < stale_before,
        ),
    ).update(
        {
            SyncStateRecord.run_token: token,
            SyncStateRecord.run_started_at: now,
            SyncStateRecord.last_status: "running",
            SyncStateRecord.last_error: None,
        },
        synchronize_session=False,
    )
    db.commit()
    return token if claimed == 1 else None


class _FreshserviceRunClaimLost(RuntimeError):
    pass


def _require_freshservice_run_owner(
    db: Session,
    state: SyncStateRecord,
    token: str,
    *,
    renew: bool,
) -> SyncStateRecord:
    """Verify claim ownership and optionally renew it before remote work."""
    if renew:
        with db.no_autoflush:
            changed = db.query(SyncStateRecord).filter(
                SyncStateRecord.id == state.id,
                SyncStateRecord.run_token == token,
            ).update(
                {SyncStateRecord.run_started_at: datetime.utcnow()},
                synchronize_session=False,
            )
        if changed != 1:
            db.rollback()
            raise _FreshserviceRunClaimLost("Freshservice sync claim lost")
        db.commit()
        return state

    with db.no_autoflush:
        owned = db.query(SyncStateRecord.id).filter(
            SyncStateRecord.id == state.id,
            SyncStateRecord.run_token == token,
        ).scalar()
    if owned is None:
        db.rollback()
        raise _FreshserviceRunClaimLost("Freshservice sync claim lost")
    return state


def _capture_freshservice_budget(state: SyncStateRecord, adapter) -> bool:
    snapshot = adapter.rate_limit_snapshot()
    state.rate_limit_total = snapshot.get("total")
    state.rate_limit_remaining = snapshot.get("remaining")
    state.rate_limit_used = snapshot.get("used")
    if adapter.should_pause_requests():
        # Freshservice minute windows do not expose a reset timestamp on a
        # successful response. Waiting a full minute protects capacity shared
        # with other integrations and custom apps on the account.
        state.next_retry_at = datetime.utcnow() + timedelta(seconds=60)
        return True
    return False


def _advance_page_cursor(state: SyncStateRecord, page_data, *, recent: bool) -> bool:
    """Advance a provider cursor. Returns True when the lane is complete."""
    page_attr = "recent_page" if recent else "history_page"
    workspace_attr = (
        "recent_workspace_index" if recent else "history_workspace_index"
    )
    if page_data.has_next_page:
        setattr(state, page_attr, getattr(state, page_attr) + 1)
        return False
    next_workspace = getattr(state, workspace_attr) + 1
    if next_workspace < page_data.workspace_count:
        setattr(state, workspace_attr, next_workspace)
        setattr(state, page_attr, 1)
        return False
    return True


def _advance_background_history_cursor(
    state: SyncStateRecord,
    page_data,
) -> bool:
    """Advance until every provider page in every workspace is exhausted."""
    if page_data.has_next_page:
        state.background_history_page += 1
        return False
    next_workspace = state.background_history_workspace_index + 1
    if next_workspace < page_data.workspace_count:
        state.background_history_workspace_index = next_workspace
        state.background_history_page = 1
        return False
    return True


def _advance_provider_timestamp_repair_cursor(
    state: SyncStateRecord,
    page_data,
) -> bool:
    """Advance the versioned four-week timestamp replay cursor."""
    if page_data.has_next_page:
        state.provider_timestamp_repair_page += 1
        return False
    next_workspace = state.provider_timestamp_repair_workspace_index + 1
    if next_workspace < page_data.workspace_count:
        state.provider_timestamp_repair_workspace_index = next_workspace
        state.provider_timestamp_repair_page = 1
        return False
    return True


def _persist_freshservice_page(
    db: Session,
    *,
    state: SyncStateRecord,
    adapter,
    binding_id: str,
    tickets: List[ExternalTicket],
    claim_checkpoint: Callable[[bool], SyncStateRecord],
) -> tuple[dict[str, int], SyncStateRecord]:
    counts = {"new": 0, "updated": 0, "errors": 0}
    for ext in tickets:
        try:
            action, _ticket = _apply_external_ticket(
                db,
                state=state,
                ext=ext,
                adapter=adapter,
                overwrite=True,
                binding_id=binding_id,
                commit_checkpoint=lambda: claim_checkpoint(True),
            )
            if action in {"new", "updated"}:
                counts[action] += 1
        except _FreshserviceRunClaimLost:
            db.rollback()
            raise
        except Exception as exc:
            if hasattr(exc, "retry_after"):
                raise
            db.rollback()
            counts["errors"] += 1
            print(
                "[sync] Freshservice ticket page upsert failed "
                f"kind={type(exc).__name__}"
            )
            state = _find_sync_state(db, adapter, binding_id)
            if state is None:
                raise RuntimeError("Freshservice sync state disappeared") from exc
    return counts, state


def _hydrate_freshservice_conversations(
    db: Session,
    *,
    state: SyncStateRecord,
    adapter,
    binding_id: str,
    limit: int,
    claim_checkpoint: Optional[
        Callable[[bool], SyncStateRecord]
    ] = None,
) -> tuple[int, int, SyncStateRecord]:
    if limit <= 0:
        return 0, 0, state
    automatic_cutoff = datetime.utcnow() - timedelta(days=AUTOMATIC_FETCH_DAYS)
    hydration_scope = or_(
        TicketRecord.external_updated_at >= automatic_cutoff,
        and_(
            TicketRecord.external_updated_at.is_(None),
            ticket_created_within_filter(automatic_cutoff),
        ),
    )
    if state.history_since_at and state.history_until_at:
        history_activity = func.coalesce(
            TicketRecord.external_updated_at,
            TicketRecord.external_created_at,
            TicketRecord.created_at,
        )
        hydration_scope = or_(
            hydration_scope,
            and_(
                history_activity >= state.history_since_at,
                history_activity < state.history_until_at,
            ),
        )
    if (
        state.background_history_started_at
        and state.background_history_through_at
    ):
        background_activity = func.coalesce(
            TicketRecord.external_updated_at,
            TicketRecord.external_created_at,
            TicketRecord.created_at,
        )
        hydration_scope = or_(
            hydration_scope,
            background_activity < state.background_history_through_at,
        )
    candidates = db.query(TicketRecord).filter(
        TicketRecord.binding_id == binding_id,
        TicketRecord.external_source == adapter.provider_name,
        TicketRecord.external_id.isnot(None),
        hydration_scope,
        or_(
            TicketRecord.external_conversations_synced_at.is_(None),
            and_(
                TicketRecord.external_updated_at.isnot(None),
                TicketRecord.external_conversations_synced_at
                < TicketRecord.external_updated_at,
            ),
        ),
    ).order_by(
        TicketRecord.external_updated_at.desc(),
        TicketRecord.external_created_at.desc(),
        TicketRecord.external_id.desc(),
    ).limit(limit).all()
    hydrated = 0
    errors = 0
    for ticket in candidates:
        try:
            detail_artifacts: set[str] = set()
            detail_description_changed = False
            if claim_checkpoint is not None:
                state = claim_checkpoint(True)
            detail = (
                asyncio.run(adapter.fetch_ticket_details(ticket.external_id))
                if hasattr(adapter, "fetch_ticket_details") else None
            )
            if claim_checkpoint is not None:
                state = claim_checkpoint(False)
                state = claim_checkpoint(True)
            conversations = asyncio.run(
                adapter.fetch_ticket_conversations(ticket.external_id)
            )
            if claim_checkpoint is not None:
                state = claim_checkpoint(False)
            if detail is not None:
                normalized_detail = _normalize_external_ticket(detail)
                detail_description_changed = (
                    ticket.description != normalized_detail.description
                )
                if detail_description_changed:
                    detail_artifacts.update({
                        "triage", "summary", "route", "resolution",
                    })
                    if _ticket_has_ai_material(db, ticket):
                        invalidate_ticket_ai(ticket)
                ticket.description = normalized_detail.description
                ticket.external_description_html = normalized_detail.description_html
                ticket.external_requester_id = normalized_detail.requester_id
                ticket.external_requester_name = normalized_detail.requester_name
                ticket.external_requester_email = normalized_detail.requester_email
                ticket.external_requester_title = normalized_detail.requester_title
                ticket.reporter = (
                    normalized_detail.requester_email
                    or normalized_detail.reporter
                )
                _upsert_embedded_external_user(
                    db,
                    binding_id=binding_id,
                    provider=adapter.provider_name,
                    external_id=normalized_detail.requester_id,
                    user_type="requester",
                    name=normalized_detail.requester_name,
                    email=normalized_detail.requester_email,
                    title=normalized_detail.requester_title,
                )
                _upsert_attachment_metadata(
                    db,
                    ticket=ticket,
                    owner_type="ticket",
                    owner_external_id=ticket.external_id or "",
                    attachments=normalized_detail.attachments,
                )
                if detail_artifacts:
                    # Detail hydration may include historical/admin-requested
                    # records. Invalidate stale artifacts regardless, but only
                    # admit replacement generation through the same audited
                    # binding generation, cutover, pause, and lookback policy
                    # used by ticket/conversation activity.
                    _created, detail_eligible = _record_activity(
                        db,
                        state=state,
                        ticket=ticket,
                        entity_type="ticket_detail",
                        external_id=ticket.external_id or "",
                        revision_hash=_ticket_revision_hash(normalized_detail),
                        activity_at=(
                            normalized_detail.updated_at
                            or ticket.external_updated_at
                        ),
                        artifacts=detail_artifacts,
                    )
                    if not detail_eligible:
                        detail_artifacts = set()
            artifacts = detail_artifacts | _project_conversations(
                db,
                state=state,
                ticket=ticket,
                conversations=conversations,
                # A single observation can safely update known records but is
                # not sufficient evidence to tombstone an absent provider row.
                confirmed_absent_ids=set(),
            )
            for conversation in conversations:
                _upsert_attachment_metadata(
                    db,
                    ticket=ticket,
                    owner_type="conversation",
                    owner_external_id=conversation.external_id,
                    attachments=conversation.attachments,
                )
            requested = _staged_automatic_artifacts(ticket, artifacts)
            if requested:
                _queue_analysis(db, ticket, requested)
            ticket.external_conversations_synced_at = datetime.utcnow()
            if claim_checkpoint is not None:
                # Lossless conversation projection can be locally expensive.
                # A worker whose lease expired during it must roll back rather
                # than publish after a replacement worker has taken the run.
                state = claim_checkpoint(True)
            else:
                db.commit()
            if detail_description_changed:
                # Detail hydration can correct the abbreviated list payload.
                # Keep previously indexed retrieval evidence aligned with the
                # authoritative description; the helper is a no-op for tickets
                # that have never been admitted to the shared index.
                refresh_ticket_documents_if_indexed(db, ticket)
            hydrated += 1
        except _FreshserviceRunClaimLost:
            db.rollback()
            raise
        except Exception as exc:
            if hasattr(exc, "retry_after"):
                raise
            db.rollback()
            errors += 1
            print(
                "[sync] Freshservice conversation hydration failed "
                f"kind={type(exc).__name__}"
            )
            state = _find_sync_state(db, adapter, binding_id)
            if state is None:
                raise RuntimeError("Freshservice sync state disappeared") from exc
            break
        if _capture_freshservice_budget(state, adapter):
            db.commit()
            break
    return hydrated, errors, state


def _upsert_attachment_metadata(
    db: Session,
    *,
    ticket: TicketRecord,
    owner_type: str,
    owner_external_id: str,
    attachments: list[ExternalAttachment],
) -> None:
    provider = ticket.external_source or ""
    storage_ready = attachment_storage_configured()
    current_ids = {attachment.external_id for attachment in attachments}
    owner_rows = db.query(ExternalAttachmentRecord).filter(
        ExternalAttachmentRecord.binding_id == ticket.binding_id,
        ExternalAttachmentRecord.provider == provider,
        ExternalAttachmentRecord.provider_ticket_id == (ticket.external_id or ""),
        ExternalAttachmentRecord.owner_type == owner_type,
        ExternalAttachmentRecord.owner_external_id == owner_external_id,
        ExternalAttachmentRecord.external_id.in_(current_ids),
    ).all() if current_ids else []
    rows_by_external_id = {row.external_id: row for row in owner_rows}
    for attachment in attachments:
        row = rows_by_external_id.get(attachment.external_id)
        blob_key = safe_blob_name(
            binding_id=ticket.binding_id,
            provider_ticket_id=ticket.external_id or "unknown",
            owner_type=owner_type,
            owner_external_id=owner_external_id,
            external_id=attachment.external_id,
            file_name=attachment.name,
        )
        if row is None:
            row = ExternalAttachmentRecord(
                id=str(uuid.uuid4()),
                binding_id=ticket.binding_id,
                provider=provider,
                ticket_id=ticket.id,
                provider_ticket_id=ticket.external_id or "",
                owner_type=owner_type,
                owner_external_id=owner_external_id,
                external_id=attachment.external_id,
                file_name=attachment.name,
                content_type=attachment.content_type,
                declared_size=attachment.size,
                source_url=attachment.download_url,
                blob_key=blob_key,
                storage_status="pending" if storage_ready else "waiting_storage",
                attempts=0,
            )
            db.add(row)
            owner_rows.append(row)
            rows_by_external_id[row.external_id] = row
            continue
        row.ticket_id = ticket.id
        row.provider_ticket_id = ticket.external_id or ""
        row.file_name = attachment.name
        row.content_type = attachment.content_type
        row.declared_size = attachment.size
        row.blob_key = row.blob_key or blob_key
        row.updated_at = datetime.utcnow()
        if row.storage_status != "stored":
            url_changed = row.source_url != attachment.download_url
            row.source_url = attachment.download_url
            if storage_ready and (row.storage_status == "waiting_storage" or url_changed):
                row.storage_status = "pending"
                row.attempts = 0
                row.last_error = None
                row.next_attempt_at = None

    # Freshservice occasionally rotates an attachment identifier and signed
    # source URL while retaining the same file in the same ticket/conversation
    # snapshot. Once the current replacement is durable, retire the obsolete
    # row so an expired URL cannot remain as a permanent sync error or create a
    # duplicate attachment in the ticket UI. The old metadata remains stored
    # for audit purposes.
    db.flush()
    current_rows = [
        rows_by_external_id[external_id]
        for external_id in current_ids
        if external_id in rows_by_external_id
    ]
    durable_replacements = {
        (row.file_name, row.content_type or "", row.declared_size): row
        for row in current_rows
        if row.storage_status == "stored"
    }
    if durable_replacements:
        stale_rows = db.query(ExternalAttachmentRecord).filter(
            ExternalAttachmentRecord.binding_id == ticket.binding_id,
            ExternalAttachmentRecord.provider == provider,
            ExternalAttachmentRecord.provider_ticket_id == (ticket.external_id or ""),
            ExternalAttachmentRecord.owner_type == owner_type,
            ExternalAttachmentRecord.owner_external_id == owner_external_id,
            ExternalAttachmentRecord.external_id.notin_(current_ids),
            ExternalAttachmentRecord.storage_status != "superseded",
        ).all()
        for stale in stale_rows:
            fingerprint = (
                stale.file_name,
                stale.content_type or "",
                stale.declared_size,
            )
            if fingerprint not in durable_replacements:
                continue
            stale.storage_status = "superseded"
            stale.source_url = None
            stale.last_error = None
            stale.next_attempt_at = None
            stale.updated_at = datetime.utcnow()


def _sync_freshservice_attachment_backlog(
    db: Session,
    *,
    adapter,
    binding_id: str,
    limit: int,
    claim_checkpoint: Optional[
        Callable[[bool], SyncStateRecord]
    ] = None,
) -> tuple[int, int]:
    if limit <= 0 or not attachment_storage_configured():
        return 0, 0
    store = AzureBlobAttachmentStore()
    max_bytes = attachment_max_bytes()
    rows = db.query(ExternalAttachmentRecord).filter(
        ExternalAttachmentRecord.binding_id == binding_id,
        ExternalAttachmentRecord.provider == adapter.provider_name,
        ExternalAttachmentRecord.storage_status.in_((
            "pending", "waiting_storage", "error",
        )),
        ExternalAttachmentRecord.attempts < 5,
        or_(
            ExternalAttachmentRecord.next_attempt_at.is_(None),
            ExternalAttachmentRecord.next_attempt_at <= datetime.utcnow(),
        ),
    ).order_by(
        ExternalAttachmentRecord.created_at.asc(),
        ExternalAttachmentRecord.id.asc(),
    ).limit(limit).all()
    stored = 0
    errors = 0
    for row in rows:
        if claim_checkpoint is not None:
            claim_checkpoint(True)
        row.last_attempted_at = datetime.utcnow()
        row.attempts = int(row.attempts or 0) + 1
        stage = "validate"
        try:
            if not row.source_url or not row.blob_key:
                raise ValueError("attachment_source_unavailable")
            if row.declared_size is not None and row.declared_size > max_bytes:
                raise ValueError("attachment_too_large")
            stage = "download"
            content = asyncio.run(
                adapter.download_attachment(row.source_url, max_bytes)
            )
            if claim_checkpoint is not None:
                # Download time consumes the prior lease. Renew again before
                # the independent blob upload so a replacement owner cannot
                # overlap this second remote side effect.
                claim_checkpoint(True)
            stage = "validate"
            if row.declared_size is not None and len(content) != row.declared_size:
                raise ValueError("attachment_size_mismatch")
            stage = "upload"
            store.upload(row.blob_key, content, row.content_type)
            if claim_checkpoint is not None:
                claim_checkpoint(False)
            row.content_sha256 = hashlib.sha256(content).hexdigest()
            row.stored_size = len(content)
            row.storage_status = "stored"
            row.stored_at = datetime.utcnow()
            row.last_error = None
            row.next_attempt_at = None
            # Provider attachment URLs may be signed or otherwise sensitive.
            # They are needed only until the private copy is durable.
            row.source_url = None
            stored += 1
        except _FreshserviceRunClaimLost:
            db.rollback()
            raise
        except Exception as exc:
            if hasattr(exc, "retry_after"):
                raise
            status_code = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            error_code = getattr(exc, "error_code", None)
            if hasattr(error_code, "value"):
                error_code = error_code.value
            detail_parts = [
                "attachment_copy_failed",
                stage,
                type(exc).__name__,
            ]
            if status_code is not None:
                detail_parts.append(f"http_{status_code}")
            if error_code:
                safe_error_code = "".join(
                    char for char in str(error_code)
                    if char.isalnum() or char in ("_", "-")
                )[:80]
                if safe_error_code:
                    detail_parts.append(safe_error_code)
            error_detail = ":".join(detail_parts)[:255]
            row.storage_status = "error"
            row.last_error = error_detail
            if row.attempts < 5:
                delay_seconds = min(6 * 60 * 60, 60 * (2 ** (row.attempts - 1)))
                row.next_attempt_at = datetime.utcnow() + timedelta(
                    seconds=delay_seconds
                )
            else:
                row.next_attempt_at = None
            errors += 1
            print(
                "[sync] Freshservice attachment copy failed "
                f"detail={error_detail}"
            )
        row.updated_at = datetime.utcnow()
        db.commit()
    return stored, errors


def _sync_freshservice_tickets(adapter, *, binding_id: str) -> dict:
    """Synchronize Freshservice in small durable batches, newest work first."""
    from .freshservice import FreshserviceRateLimited

    limits = freshservice_sync_limits()
    result = {
        "new": 0,
        "updated": 0,
        "errors": 0,
        "fetched": 0,
        "recent_pages": 0,
        "provider_timestamp_repair_pages": 0,
        "background_history_pages": 0,
        "history_pages": 0,
        "conversations": 0,
        "attachments": 0,
        "attachment_errors": 0,
        "deferred": 0,
        "throttled": 0,
    }
    db: Session = SessionLocal()
    token: Optional[str] = None
    try:
        state = _ensure_sync_state(db, adapter, binding_id)
        now = datetime.utcnow()
        if state.next_retry_at and state.next_retry_at > now:
            result["deferred"] = 1
            return result
        token = _claim_freshservice_run(
            db, state, lease_seconds=limits["lease_seconds"]
        )
        if token is None:
            result["deferred"] = 1
            return result
        state = _find_sync_state(db, adapter, binding_id)
        if state is None:
            raise RuntimeError("Freshservice sync state disappeared")

        # A completed or interrupted older repair used a narrower provider
        # window. Restart its cursor exactly once at the previous version so
        # page numbers cannot be reused against a different updated_since
        # boundary. New databases also enter the same versioned scan without
        # repeatedly resetting an in-progress cursor on every worker sweep.
        repair_baseline_version = PROVIDER_TIMESTAMP_REPAIR_VERSION - 1
        repair_version = state.provider_timestamp_repair_version or 0
        if (
            repair_version < repair_baseline_version
            or (
                repair_version == repair_baseline_version
                and state.provider_timestamp_repair_completed_at is not None
            )
        ):
            state.provider_timestamp_repair_version = repair_baseline_version
            state.provider_timestamp_repair_started_at = None
            state.provider_timestamp_repair_completed_at = None
            state.provider_timestamp_repair_page = 1
            state.provider_timestamp_repair_workspace_index = 0
            state.provider_timestamp_repair_processed = 0
            db.commit()

        def claim_checkpoint(renew: bool) -> SyncStateRecord:
            nonlocal state
            state = _require_freshservice_run_owner(
                db,
                state,
                token,
                renew=renew,
            )
            return state

        if state.recent_cycle_started_at is None:
            cycle_started = datetime.utcnow().replace(microsecond=0)
            state.recent_cycle_started_at = cycle_started
            automatic_window_start = cycle_started - timedelta(
                days=AUTOMATIC_FETCH_DAYS
            )
            state.recent_since_at = max(
                state.last_synced_at or automatic_window_start,
                automatic_window_start,
            )
            state.recent_page = 1
            state.recent_workspace_index = 0
            db.commit()

        pause_for_budget = False
        for _ in range(limits["recent_pages"]):
            state = claim_checkpoint(True)
            page_data = asyncio.run(adapter.fetch_ticket_page(
                since=state.recent_since_at,
                page=state.recent_page,
                workspace_index=state.recent_workspace_index,
                order_type="asc",
                include_resources=True,
            ))
            state = claim_checkpoint(False)
            result["recent_pages"] += 1
            result["fetched"] += len(page_data.tickets)
            counts, state = _persist_freshservice_page(
                db,
                state=state,
                adapter=adapter,
                binding_id=binding_id,
                tickets=page_data.tickets,
                claim_checkpoint=claim_checkpoint,
            )
            for key in ("new", "updated", "errors"):
                result[key] += counts[key]
            if counts["errors"]:
                break
            # Page persistence can consume a material part of the lease.
            # Re-assert ownership before publishing rows and advancing the
            # durable provider cursor.
            state = claim_checkpoint(True)
            lane_complete = _advance_page_cursor(state, page_data, recent=True)
            if lane_complete:
                recent_since_at = state.recent_since_at
                recent_cycle_started_at = state.recent_cycle_started_at
                state.last_synced_at = state.recent_cycle_started_at - timedelta(
                    seconds=5
                )
                state.recent_completed_at = datetime.utcnow()
                state.recent_since_at = None
                state.recent_cycle_started_at = None
                state.recent_page = 1
                state.recent_workspace_index = 0
                # A first inventory that already covered the complete current
                # window needs no duplicate timestamp replay. Upgrade paths
                # whose cursor started later remain pending and enter the
                # separate repair lane below.
                if (
                    (state.provider_timestamp_repair_version or 0)
                    < PROVIDER_TIMESTAMP_REPAIR_VERSION
                    and recent_since_at is not None
                    and recent_cycle_started_at is not None
                    and recent_since_at
                    <= recent_cycle_started_at - timedelta(
                        days=PROVIDER_TIMESTAMP_REPAIR_DAYS
                    )
                ):
                    state.provider_timestamp_repair_version = (
                        PROVIDER_TIMESTAMP_REPAIR_VERSION
                    )
                    state.provider_timestamp_repair_completed_at = datetime.utcnow()
            state.total_synced = (
                (state.total_synced or 0) + counts["new"] + counts["updated"]
            )
            pause_for_budget = _capture_freshservice_budget(state, adapter)
            db.commit()
            if lane_complete or pause_for_budget:
                break

        # Older builds advanced the incremental cursor before ticket list
        # stats were requested, so closed tickets already behind that cursor
        # can lack provider-owned resolution timestamps forever. Repair that
        # historical projection with its own durable cursor, after the normal
        # recent lane and before any older background inventory. This keeps
        # newly updated tickets first on every sweep and makes restarts safe.
        if (
            not pause_for_budget
            and not result["errors"]
            and state.recent_cycle_started_at is None
            and (state.provider_timestamp_repair_version or 0)
            < PROVIDER_TIMESTAMP_REPAIR_VERSION
        ):
            if state.provider_timestamp_repair_started_at is None:
                state.provider_timestamp_repair_started_at = datetime.utcnow()
                state.provider_timestamp_repair_page = 1
                state.provider_timestamp_repair_workspace_index = 0
                state.provider_timestamp_repair_processed = 0
                db.commit()
            repair_since_at = (
                state.provider_timestamp_repair_started_at
                - timedelta(days=PROVIDER_TIMESTAMP_REPAIR_DAYS)
            )
            for _ in range(limits["recent_pages"]):
                state = claim_checkpoint(True)
                page_data = asyncio.run(adapter.fetch_ticket_page(
                    since=repair_since_at,
                    page=state.provider_timestamp_repair_page,
                    workspace_index=(
                        state.provider_timestamp_repair_workspace_index
                    ),
                    order_type="asc",
                    include_resources=True,
                ))
                state = claim_checkpoint(False)
                result["provider_timestamp_repair_pages"] += 1
                result["fetched"] += len(page_data.tickets)
                counts, state = _persist_freshservice_page(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=binding_id,
                    tickets=page_data.tickets,
                    claim_checkpoint=claim_checkpoint,
                )
                for key in ("new", "updated", "errors"):
                    result[key] += counts[key]
                if counts["errors"]:
                    break
                state = claim_checkpoint(True)
                state.provider_timestamp_repair_processed = (
                    (state.provider_timestamp_repair_processed or 0)
                    + len(page_data.tickets)
                )
                state.total_synced = (
                    (state.total_synced or 0)
                    + counts["new"]
                    + counts["updated"]
                )
                repair_complete = _advance_provider_timestamp_repair_cursor(
                    state, page_data
                )
                if repair_complete:
                    state.provider_timestamp_repair_version = (
                        PROVIDER_TIMESTAMP_REPAIR_VERSION
                    )
                    state.provider_timestamp_repair_completed_at = datetime.utcnow()
                pause_for_budget = _capture_freshservice_budget(state, adapter)
                db.commit()
                if repair_complete or pause_for_budget:
                    break

        if (
            state.provider_timestamp_repair_version
            >= PROVIDER_TIMESTAMP_REPAIR_VERSION
            and state.recent_completed_at is not None
            and (
                (state.background_history_scan_version or 0)
                < BACKGROUND_HISTORY_SCAN_VERSION
                or state.background_history_started_at is None
                or state.background_history_through_at is None
            )
        ):
            # Builds before scan version 1 treated any recent activity inside
            # an ascending page as an end-of-inventory marker. Freshservice's
            # ticket-list contract does not let callers choose updated_at as
            # the sort key, so those checkpoints cannot prove exhaustion.
            # Reopen them exactly once and preserve restartability thereafter.
            state.background_history_scan_version = (
                BACKGROUND_HISTORY_SCAN_VERSION
            )
            state.background_history_started_at = datetime.utcnow()
            state.background_history_through_at = (
                state.recent_completed_at - timedelta(days=AUTOMATIC_FETCH_DAYS)
            )
            state.background_history_page = 1
            state.background_history_workspace_index = 0
            state.background_history_complete = False
            state.background_history_processed = 0
            db.commit()

        if (
            not pause_for_budget
            and not result["errors"]
            and state.background_history_started_at is not None
            and state.background_history_through_at is not None
            and not state.background_history_complete
        ):
            for _ in range(limits["history_pages"]):
                state = claim_checkpoint(True)
                page_data = asyncio.run(adapter.fetch_ticket_page(
                    since=BACKGROUND_HISTORY_EPOCH,
                    page=state.background_history_page,
                    workspace_index=state.background_history_workspace_index,
                    order_type="asc",
                    include_resources=True,
                ))
                state = claim_checkpoint(False)
                result["background_history_pages"] += 1
                result["fetched"] += len(page_data.tickets)
                activity_rows = [
                    (
                        ticket,
                        _utc_naive(ticket.updated_at or ticket.created_at),
                    )
                    for ticket in page_data.tickets
                ]
                historical_tickets = [
                    ticket for ticket, activity_at in activity_rows
                    if (
                        activity_at is not None
                        and activity_at < state.background_history_through_at
                    )
                ]
                counts, state = _persist_freshservice_page(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=binding_id,
                    tickets=historical_tickets,
                    claim_checkpoint=claim_checkpoint,
                )
                for key in ("new", "updated", "errors"):
                    result[key] += counts[key]
                if counts["errors"]:
                    break
                state = claim_checkpoint(True)
                state.background_history_processed = (
                    (state.background_history_processed or 0)
                    + len(page_data.tickets)
                )
                state.total_synced = (
                    (state.total_synced or 0)
                    + counts["new"]
                    + counts["updated"]
                )
                state.background_history_complete = (
                    _advance_background_history_cursor(
                        state,
                        page_data,
                    )
                )
                pause_for_budget = _capture_freshservice_budget(state, adapter)
                db.commit()
                if state.background_history_complete or pause_for_budget:
                    break

        if (
            not pause_for_budget
            and not result["errors"]
            and state.history_requested_at is not None
            and state.history_since_at is not None
            and state.history_until_at is not None
            and not state.history_complete
        ):
            for _ in range(limits["history_pages"]):
                state = claim_checkpoint(True)
                page_data = asyncio.run(adapter.fetch_ticket_page(
                    since=state.history_since_at,
                    page=state.history_page,
                    workspace_index=state.history_workspace_index,
                    order_type="asc",
                    include_resources=True,
                ))
                state = claim_checkpoint(False)
                result["history_pages"] += 1
                result["fetched"] += len(page_data.tickets)
                requested_tickets = [
                    ticket for ticket in page_data.tickets
                    if (
                        (ticket.updated_at or ticket.created_at) is not None
                        and state.history_since_at
                        <= (ticket.updated_at or ticket.created_at)
                        < state.history_until_at
                    )
                ]
                counts, state = _persist_freshservice_page(
                    db,
                    state=state,
                    adapter=adapter,
                    binding_id=binding_id,
                    tickets=requested_tickets,
                    claim_checkpoint=claim_checkpoint,
                )
                for key in ("new", "updated", "errors"):
                    result[key] += counts[key]
                if counts["errors"]:
                    break
                state = claim_checkpoint(True)
                state.history_processed = (
                    (state.history_processed or 0) + len(page_data.tickets)
                )
                state.total_synced = (
                    (state.total_synced or 0)
                    + counts["new"]
                    + counts["updated"]
                )
                state.history_complete = _advance_page_cursor(
                    state, page_data, recent=False
                )
                pause_for_budget = _capture_freshservice_budget(state, adapter)
                db.commit()
                if state.history_complete or pause_for_budget:
                    break

        if not pause_for_budget and not result["errors"]:
            hydrated, errors, state = _hydrate_freshservice_conversations(
                db,
                state=state,
                adapter=adapter,
                binding_id=binding_id,
                limit=limits["conversations"],
                claim_checkpoint=claim_checkpoint,
            )
            result["conversations"] = hydrated
            result["errors"] += errors
            state.conversations_processed = (
                state.conversations_processed or 0
            ) + hydrated
            pause_for_budget = adapter.should_pause_requests()

        if not pause_for_budget and not result["errors"]:
            stored, attachment_errors = _sync_freshservice_attachment_backlog(
                db,
                adapter=adapter,
                binding_id=binding_id,
                limit=limits["attachments"],
                claim_checkpoint=claim_checkpoint,
            )
            result["attachments"] = stored
            result["attachment_errors"] = attachment_errors
            result["errors"] += attachment_errors

        state = claim_checkpoint(False)
        state.last_batch_new = result["new"]
        state.last_batch_updated = result["updated"]
        state.last_batch_errors = result["errors"]
        state.run_finished_at = datetime.utcnow()
        state.run_token = None
        if pause_for_budget:
            state.last_status = "throttled"
            result["throttled"] = 1
        elif result["errors"]:
            state.last_status = "error"
            state.last_error = "One or more provider records could not be synchronized"
        else:
            state.last_status = "success"
            state.last_error = None
            if state.next_retry_at and state.next_retry_at <= datetime.utcnow():
                state.next_retry_at = None
        db.commit()
    except _FreshserviceRunClaimLost:
        db.rollback()
        result["deferred"] = 1
    except FreshserviceRateLimited as exc:
        db.rollback()
        state = _find_sync_state(db, adapter, binding_id)
        if state is not None and token is not None:
            try:
                state = _require_freshservice_run_owner(
                    db, state, token, renew=False
                )
            except _FreshserviceRunClaimLost:
                result["deferred"] = 1
                return result
        if state is not None:
            _capture_freshservice_budget(state, adapter)
            state.next_retry_at = datetime.utcnow() + timedelta(
                seconds=exc.retry_after
            )
            state.last_status = "throttled"
            state.last_error = None
            state.run_finished_at = datetime.utcnow()
            state.run_token = None
            state.last_batch_new = result["new"]
            state.last_batch_updated = result["updated"]
            state.last_batch_errors = result["errors"]
            db.commit()
        result["throttled"] = 1
    except Exception as exc:
        db.rollback()
        state = _find_sync_state(db, adapter, binding_id)
        if state is not None and token is not None:
            try:
                state = _require_freshservice_run_owner(
                    db, state, token, renew=False
                )
            except _FreshserviceRunClaimLost:
                result["deferred"] = 1
                return result
        if state is not None:
            state.last_status = "error"
            state.last_error = f"sync_failed:{type(exc).__name__}"
            state.last_batch_new = result["new"]
            state.last_batch_updated = result["updated"]
            state.last_batch_errors = result["errors"] + 1
            state.run_finished_at = datetime.utcnow()
            state.run_token = None
            db.commit()
        result["errors"] += 1
        print(f"[sync] fatal Freshservice error kind={type(exc).__name__}")
    finally:
        db.close()
    return result


def sync_tickets_from_external(adapter=None, *, binding_id: str = "legacy") -> dict:
    adapter = adapter or get_adapter()
    if (
        adapter.provider_name.strip().lower() == "freshservice"
        and hasattr(adapter, "fetch_ticket_page")
        and hasattr(adapter, "rate_limit_snapshot")
    ):
        return _sync_freshservice_tickets(adapter, binding_id=binding_id)
    return _sync_tickets_legacy(adapter, binding_id=binding_id)


def _sync_tickets_legacy(adapter=None, *, binding_id: str = "legacy") -> dict:
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


def queue_old_ticket_fetch(
    adapter,
    *,
    start_at: datetime,
    end_at: datetime,
    requested_by: str,
    binding_id: str = "legacy",
) -> dict[str, Any]:
    """Create an admin-requested, durable old-ticket range cursor.

    The scheduler processes this lane only while these explicit request
    fields are present. It never changes the automatic 30-day cursor.
    """
    start_at = _utc_naive(start_at)
    end_at = _utc_naive(end_at)
    if start_at is None or end_at is None or start_at >= end_at:
        raise ValueError("old_ticket_fetch_range_invalid")
    db: Session = SessionLocal()
    try:
        _ensure_sync_state(db, adapter, binding_id)
        state = db.query(SyncStateRecord).filter(
            SyncStateRecord.binding_id == binding_id,
            SyncStateRecord.provider == adapter.provider_name,
        ).with_for_update().one()
        if state.history_requested_at is not None and not state.history_complete:
            raise ValueError("old_ticket_fetch_already_queued")
        state.history_since_at = start_at
        state.history_until_at = end_at
        state.history_requested_at = datetime.utcnow()
        state.history_requested_by = requested_by
        state.history_page = 1
        state.history_workspace_index = 0
        state.history_complete = False
        state.history_processed = 0
        state.last_status = "queued"
        state.last_error = None
        db.commit()
        return {
            "queued": True,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "requested_at": state.history_requested_at.isoformat(),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def fetch_tickets_by_days(
    adapter=None,
    days: int = 7,
    overwrite: bool = False,
    *,
    binding_id: str = "legacy",
) -> dict:
    """Prioritize a recent provider window without creating a traffic burst.

    Source status is always reconciled for tickets already imported (matched
    by external_source + external_id). With overwrite=False, all other local
    fields are preserved. Pass overwrite=True to force-refresh every provider
    field on existing records.
    """
    days = max(1, min(int(days), 365))
    adapter = adapter or get_adapter()
    if (
        adapter.provider_name.strip().lower() == "freshservice"
        and hasattr(adapter, "fetch_ticket_page")
        and hasattr(adapter, "rate_limit_snapshot")
    ):
        # Freshservice tenants can contain hundreds of pages. Manual requests
        # re-prioritize the recent lane and execute only one bounded sweep;
        # remaining pages resume in the dedicated worker.
        db: Session = SessionLocal()
        try:
            state = _ensure_sync_state(db, adapter, binding_id)
            active_lease = bool(
                state.run_token
                and state.run_started_at
                and state.run_started_at
                > datetime.utcnow()
                - timedelta(seconds=freshservice_sync_limits()["lease_seconds"])
            )
            if not active_lease:
                now = datetime.utcnow().replace(microsecond=0)
                state.recent_since_at = now - timedelta(days=days)
                state.recent_cycle_started_at = now
                state.recent_page = 1
                state.recent_workspace_index = 0
                state.last_status = "queued"
                state.last_error = None
                db.commit()
        finally:
            db.close()
        batch = sync_tickets_from_external(adapter, binding_id=binding_id)
        return {
            "new": batch["new"],
            "updated": batch["updated"],
            "skipped": 0,
            "errors": batch["errors"],
            "fetched": batch["fetched"],
            "days": days,
            "overwrite": True,
            "queued": bool(batch["deferred"] or batch["recent_pages"]),
        }
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
        "member_of",
        "occasional",
        "observer_of",
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
        "groups_created": 0,
        "groups_updated": 0,
        "groups_unchanged": 0,
        "groups_deactivated": 0,
        "memberships": 0,
        "group_errors": 0,
    }


def _limited_append(items: list[str], detail: str, limit: int = 12) -> None:
    if len(items) < limit:
        items.append(detail)


def _import_external_users(
    adapter,
    raw_users: list[dict[str, Any]],
    *,
    binding_id: str = "legacy",
    authoritative_user_types: Optional[Collection[str]] = None,
) -> dict:
    """Store provider users only in the external directory security domain."""
    db: Session = SessionLocal()
    result = _empty_external_user_sync_result()
    seen: set[tuple[str, str]] = set()
    authoritative_types = (
        {
            str(user_type).strip().lower()
            for user_type in authoritative_user_types
            if str(user_type).strip()
        }
        if authoritative_user_types is not None
        else None
    )
    try:
        result["total"] = len(raw_users)
        provider = adapter.provider_name
        scoped_records = db.query(ExternalUserRecord).filter(
            ExternalUserRecord.binding_id == binding_id,
            ExternalUserRecord.provider == provider,
        ).all()
        records_by_identity = {
            (record.user_type, record.external_id): record
            for record in scoped_records
        }
        now = datetime.utcnow()
        for raw_user in raw_users:
            try:
                user = _normalize_external_user(raw_user)
                ext_id = user["id"]
                if not ext_id:
                    raise ValueError("external user has no provider id")
                identity = (user["user_type"], ext_id)
                seen.add(identity)
                record = records_by_identity.get(identity)
                created = record is None
                changed = False
                with db.begin_nested():
                    if created:
                        record = ExternalUserRecord(
                            id=str(uuid.uuid4()),
                            binding_id=binding_id,
                            provider=provider,
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
                            getattr(record, key) != value
                            for key, value in values.items()
                        )
                        for key, value in values.items():
                            setattr(record, key, value)
                        record.fetched_at = now
                        if changed:
                            record.updated_at = now
                    db.flush()
                records_by_identity[identity] = record
                if created:
                    result["created"] += 1
                elif changed:
                    result["updated"] += 1
                else:
                    result["unchanged"] += 1
            except Exception as exc:
                print(f"[external-users] processing failed kind={type(exc).__name__}")
                result["errors"] += 1
                _limited_append(
                    result["error_details"],
                    f"external_user_processing_failed:{type(exc).__name__}",
                )

        # Only a complete, error-free directory read can prove that a formerly
        # active provider identity disappeared.
        if not result["errors"]:
            for identity, record in records_by_identity.items():
                if (
                    authoritative_types is not None
                    and record.user_type.lower() not in authoritative_types
                ):
                    continue
                if record.active and identity not in seen:
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


def _external_user_fetch_error_detail(user_type: str, exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    provider_code = None
    if response is not None:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                provider_code = payload.get("code")
        except Exception:
            provider_code = None
    if provider_code == "account_suspended":
        error_kind = "account_suspended"
    elif isinstance(status_code, int) and 100 <= status_code <= 599:
        error_kind = f"http_status_{status_code}"
    else:
        error_kind = type(exc).__name__
    return f"external_{user_type}_fetch_failed:{error_kind}"


async def _fetch_external_user_partitions(
    adapter,
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    """Fetch independently authoritative provider identity partitions.

    Freshservice grants agent and requester reads separately. A denied
    requester endpoint must not discard a complete agent response, and a
    failed partition must never be treated as proof that its stored identities
    disappeared.
    """
    fetchers: list[tuple[str, Callable[..., Any]]] = [
        ("agent", adapter.fetch_agents),
    ]
    fetch_requesters = getattr(adapter, "fetch_requesters", None)
    if callable(fetch_requesters):
        fetchers.append(("requester", fetch_requesters))

    raw_users: list[dict[str, Any]] = []
    authoritative_types: set[str] = set()
    error_details: list[str] = []
    for user_type, fetcher in fetchers:
        try:
            partition = await fetcher()
            if not isinstance(partition, list) or not all(
                isinstance(user, dict) for user in partition
            ):
                raise RuntimeError(
                    f"Provider {user_type} directory response is invalid"
                )
            raw_users.extend(
                {**user, "user_type": user_type} for user in partition
            )
            authoritative_types.add(user_type)
        except Exception as exc:
            print(
                f"[external-users] {user_type} fetch failed "
                f"kind={type(exc).__name__}"
            )
            _limited_append(
                error_details,
                _external_user_fetch_error_detail(user_type, exc),
            )
    return raw_users, authoritative_types, error_details


def _provider_relation_ids(value: Any) -> set[str]:
    if value is None:
        return set()
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: set[str] = set()
    for item in values:
        candidate = item.get("id") if isinstance(item, dict) else item
        text = str(candidate).strip() if candidate is not None else ""
        if text:
            result.add(text)
    return result


def _external_group_values(raw_group: dict[str, Any]) -> dict[str, Any]:
    external_id = _external_user_value(raw_group, "id", "group_id", "groupId")
    name = _external_user_value(raw_group, "name", "display_name", "displayName")
    workspace_id = _external_user_value(raw_group, "workspace_id", "workspaceId")
    description = _external_user_value(raw_group, "description")
    profile = {
        key: raw_group[key]
        for key in ("business_hour_id", "escalate_to", "restricted", "unassigned_for")
        if raw_group.get(key) is not None
    }
    return {
        "external_id": external_id,
        "workspace_id": workspace_id or None,
        "name": name or (f"Group {external_id}" if external_id else "External group"),
        "description": description or None,
        "active": _external_user_active(raw_group),
        "profile_json": json.dumps(profile, sort_keys=True, separators=(",", ":")),
        "source_updated_at": _external_source_updated_at(raw_group),
    }


def _import_external_groups(
    adapter,
    raw_groups: list[dict[str, Any]],
    raw_users: list[dict[str, Any]],
    *,
    binding_id: str = "legacy",
) -> dict[str, int]:
    """Persist groups and authoritative member/observer relations.

    Agent membership IDs are also accepted as a bounded fallback because the
    group directory can be restricted independently from the agent directory.
    Placeholder group names are replaced on the next successful group read.
    """
    db: Session = SessionLocal()
    result = {
        "groups_created": 0,
        "groups_updated": 0,
        "groups_unchanged": 0,
        "groups_deactivated": 0,
        "memberships": 0,
        "group_errors": 0,
    }
    try:
        normalized_groups: dict[str, dict[str, Any]] = {}
        desired_memberships: set[tuple[str, str, str]] = set()

        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                result["group_errors"] += 1
                continue
            values = _external_group_values(raw_group)
            external_id = values["external_id"]
            if not external_id:
                result["group_errors"] += 1
                continue
            normalized_groups[external_id] = values
            for membership_kind, field in (("member", "members"), ("observer", "observers")):
                for external_user_id in _provider_relation_ids(raw_group.get(field)):
                    desired_memberships.add((external_id, external_user_id, membership_kind))

        normalized_agents: dict[str, dict[str, Any]] = {}
        for raw_user in raw_users:
            if not isinstance(raw_user, dict) or _external_user_type(raw_user) != "agent":
                continue
            user = _normalize_external_user(raw_user)
            if not user["id"]:
                continue
            normalized_agents[user["id"]] = user
            for membership_kind, field in (("member", "member_of"), ("observer", "observer_of")):
                for external_group_id in _provider_relation_ids(raw_user.get(field)):
                    normalized_groups.setdefault(external_group_id, {
                        "external_id": external_group_id,
                        "workspace_id": None,
                        "name": f"Group {external_group_id}",
                        "description": None,
                        "active": True,
                        "profile_json": '{"source":"agent_membership_projection"}',
                        "source_updated_at": None,
                    })
                    desired_memberships.add((external_group_id, user["id"], membership_kind))

        now = datetime.utcnow()
        scoped_group_records = db.query(ExternalGroupRecord).filter(
            ExternalGroupRecord.binding_id == binding_id,
            ExternalGroupRecord.provider == adapter.provider_name,
        ).all()
        groups_by_external_id = {
            record.external_id: record for record in scoped_group_records
        }
        group_records: dict[str, ExternalGroupRecord] = {}
        for external_id, values in normalized_groups.items():
            record = groups_by_external_id.get(external_id)
            if record is None:
                record = ExternalGroupRecord(
                    id=str(uuid.uuid4()),
                    binding_id=binding_id,
                    provider=adapter.provider_name,
                    external_id=external_id,
                    fetched_at=now,
                    created_at=now,
                    updated_at=now,
                    **{key: values[key] for key in (
                        "workspace_id", "name", "description", "active",
                        "profile_json", "source_updated_at",
                    )},
                )
                db.add(record)
                groups_by_external_id[external_id] = record
                result["groups_created"] += 1
            else:
                changed = any(
                    getattr(record, key) != values[key]
                    for key in (
                        "workspace_id", "name", "description", "active",
                        "profile_json", "source_updated_at",
                    )
                )
                for key in (
                    "workspace_id", "name", "description", "active",
                    "profile_json", "source_updated_at",
                ):
                    setattr(record, key, values[key])
                record.fetched_at = now
                if changed:
                    record.updated_at = now
                    result["groups_updated"] += 1
                else:
                    result["groups_unchanged"] += 1
            group_records[external_id] = record

        if not result["group_errors"] and raw_groups:
            for record in groups_by_external_id.values():
                if record.external_id not in normalized_groups:
                    record.active = False
                    record.fetched_at = now
                    record.updated_at = now
                    result["groups_deactivated"] += 1

        external_users = {
            row.external_id: row
            for row in db.query(ExternalUserRecord).filter(
                ExternalUserRecord.binding_id == binding_id,
                ExternalUserRecord.provider == adapter.provider_name,
                ExternalUserRecord.user_type == "agent",
            ).all()
            if row.external_id in normalized_agents
        } if normalized_agents else {}
        scoped_user_ids = [row.id for row in external_users.values()]
        desired_membership_keys: set[tuple[str, str, str]] = set()
        for external_group_id, external_user_id, membership_kind in sorted(desired_memberships):
            group = group_records.get(external_group_id)
            user = external_users.get(external_user_id)
            if group is None or user is None:
                continue
            desired_membership_keys.add((group.id, user.id, membership_kind))

        existing_memberships = db.query(ExternalGroupMembershipRecord).filter(
            ExternalGroupMembershipRecord.external_user_id.in_(scoped_user_ids)
        ).all() if scoped_user_ids else []
        existing_by_key = {
            (
                row.external_group_id,
                row.external_user_id,
                row.membership_kind,
            ): row
            for row in existing_memberships
        }
        for key, row in existing_by_key.items():
            if key not in desired_membership_keys:
                db.delete(row)
        for external_group_id, external_user_id, membership_kind in sorted(
            desired_membership_keys - set(existing_by_key)
        ):
            db.add(ExternalGroupMembershipRecord(
                external_group_id=external_group_id,
                external_user_id=external_user_id,
                membership_kind=membership_kind,
                created_at=now,
                updated_at=now,
            ))
        result["memberships"] = len(desired_membership_keys)
        db.commit()
    except Exception as exc:
        print(f"[external-groups] sync failed kind={type(exc).__name__}")
        db.rollback()
        result["group_errors"] += 1
    finally:
        db.close()
    return result


async def async_sync_external_users(
    adapter=None,
    *,
    binding_id: str = "legacy",
) -> dict:
    """Refresh external profiles without creating or updating Tickety OPS Tower users."""
    adapter = adapter or get_adapter()
    raw_users, authoritative_types, fetch_errors = (
        await _fetch_external_user_partitions(adapter)
    )
    if not authoritative_types:
        result = _empty_external_user_sync_result()
        result["errors"] = len(fetch_errors)
        result["error_details"] = fetch_errors
        return result
    result = _import_external_users(
        adapter,
        raw_users,
        binding_id=binding_id,
        authoritative_user_types=authoritative_types,
    )
    result["errors"] += len(fetch_errors)
    for detail in fetch_errors:
        _limited_append(result["error_details"], detail)
    try:
        raw_groups = await adapter.fetch_groups()
    except Exception as exc:
        print(f"[external-groups] fetch failed kind={type(exc).__name__}")
        raw_groups = []
        result["group_errors"] += 1
        _limited_append(
            result["error_details"],
            f"external_group_fetch_failed:{type(exc).__name__}",
        )
    group_result = _import_external_groups(
        adapter, raw_groups, raw_users, binding_id=binding_id
    )
    for key, value in group_result.items():
        result[key] = result.get(key, 0) + value
    return result


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
