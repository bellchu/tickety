"""Shared AI artifact lifecycle helpers."""

from sqlalchemy import and_, or_
from sqlalchemy.orm import object_session


_TERMINAL_AI_ERROR_SUFFIXES = (
    ":content_filtered",
    ":invalid_input",
    ":provider_rejected",
)


def _terminal_artifact(item: str) -> str | None:
    for suffix in _TERMINAL_AI_ERROR_SUFFIXES:
        if item.endswith(suffix):
            return item.removesuffix(suffix)
    return None


def _ai_error_items(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def merge_terminal_ai_policy_errors(
    existing: str | None,
    new_error: str | None = None,
    *,
    cleared_artifacts: set[str] | None = None,
) -> str | None:
    """Preserve artifact terminal markers while replacing transient errors."""
    cleared = cleared_artifacts or set()
    terminal = {
        item
        for item in _ai_error_items(existing)
        if _terminal_artifact(item) is not None
        and _terminal_artifact(item) not in cleared
    }
    current = _ai_error_items(new_error)
    terminal.update(
        item for item in current if _terminal_artifact(item) is not None
    )
    transient = [
        item for item in current if _terminal_artifact(item) is None
    ]
    combined = [*sorted(terminal), *transient]
    return ",".join(dict.fromkeys(combined)) or None


def clear_terminal_ai_policy_errors(
    value: str | None,
    artifacts: set[str],
) -> str | None:
    """Remove selected terminal markers without discarding unrelated errors."""
    retained = [
        item for item in _ai_error_items(value)
        if _terminal_artifact(item) not in artifacts
    ]
    return ",".join(retained) or None


def has_terminal_ai_policy_outcome(ticket, artifacts: set[str] | None = None) -> bool:
    """Whether the current input has a terminal result for a selected artifact."""
    for normalized in _ai_error_items(ticket.ai_error):
        artifact = _terminal_artifact(normalized)
        if artifact is None:
            continue
        if artifacts is None or artifact in artifacts:
            return True
    return False


def automatic_ai_policy_eligible_filter(artifacts: set[str] | None = None):
    """Exclude terminal policy outcomes from automatic admission queries.

    Explicit retries clear ``ai_error`` before queueing, while source-input
    invalidation also clears it. The exclusion therefore applies only to an
    unchanged input version and cannot permanently strand an updated ticket.
    """
    from .database import TicketRecord

    if not artifacts:
        return or_(
            TicketRecord.ai_error.is_(None),
            and_(*(
                ~TicketRecord.ai_error.contains(suffix)
                for suffix in _TERMINAL_AI_ERROR_SUFFIXES
            )),
        )
    # A ticket remains eligible when at least one selected artifact has not
    # reached a terminal provider-policy result. One filtered summary must not
    # block an independent resolver route.
    return or_(
        TicketRecord.ai_error.is_(None),
        *(and_(*(
            ~TicketRecord.ai_error.contains(f"{artifact}{suffix}")
            for suffix in _TERMINAL_AI_ERROR_SUFFIXES
        )) for artifact in sorted(artifacts)),
    )


def _deactivate_artifacts(ticket, artifacts: set[str]) -> None:
    session = object_session(ticket)
    if session is None:
        return
    from .database import AIArtifactRecord

    session.query(AIArtifactRecord).filter(
        AIArtifactRecord.ticket_id == ticket.id,
        AIArtifactRecord.artifact.in_(artifacts),
        AIArtifactRecord.active.is_(True),
    ).update({AIArtifactRecord.active: False}, synchronize_session=False)


def invalidate_ticket_ai(ticket) -> None:
    """Invalidate generated artifacts after source ticket content changes.

    Operational workflow/status fields are deliberately preserved because they
    may have been confirmed or changed by a human after the prior analysis.
    """
    _deactivate_artifacts(ticket, {"triage", "route", "summary", "resolution"})
    ticket.sentiment = None
    ticket.mood = None
    ticket.complexity = 1
    ticket.ai_reasoning = None
    ticket.suggested_response = None
    ticket.ai_review_state = None
    ticket.escalation_risk = 0
    ticket.summary = None
    ticket.recommended_solution = None
    ticket.ai_source_hash = None
    ticket.ai_pipeline_version = None
    ticket.ai_model = None
    ticket.ai_status = "stale"
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_attempts = 0
    ticket.ai_next_attempt_at = None
    ticket.ai_requested_artifacts = None
    ticket.ai_started_at = None
    ticket.ai_generated_at = None
    ticket.ai_error = None
    ticket.ai_synthetic = False
    ticket.ai_suggested_priority = None
    ticket.ai_suggested_category = None
    ticket.ai_suggested_team = None
    ticket.ai_secondary_team = None
    ticket.ai_routing_confidence = None
    ticket.ai_business_context = None
    ticket.ai_routing_scope = None
    ticket.ai_affected_service = None
    ticket.ai_failure_domain = None
    ticket.ai_routing_reason = None
    ticket.ai_routing_input_hash = None


def invalidate_ticket_resolution(ticket) -> None:
    """Invalidate downstream guidance while preserving valid triage artifacts."""
    pending_artifacts = {
        item for item in (ticket.ai_requested_artifacts or "").split(",") if item
    }
    pending_attempts = ticket.ai_attempts
    pending_next_attempt = ticket.ai_next_attempt_at
    pending_error = clear_terminal_ai_policy_errors(
        ticket.ai_error,
        {"resolution"},
    )
    _deactivate_artifacts(ticket, {"resolution"})
    ticket.recommended_solution = None
    ticket.ai_source_hash = None
    ticket.ai_status = "queued" if pending_artifacts else "partial"
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_attempts = pending_attempts if pending_artifacts else 0
    ticket.ai_next_attempt_at = (
        pending_next_attempt if pending_artifacts else None
    )
    ticket.ai_requested_artifacts = (
        ",".join(sorted(pending_artifacts)) if pending_artifacts else None
    )
    ticket.ai_started_at = None
    ticket.ai_error = pending_error


def invalidate_ticket_routing(ticket) -> None:
    """Invalidate resolver routing while preserving other valid AI artifacts."""
    pending_artifacts = {
        item for item in (ticket.ai_requested_artifacts or "").split(",") if item
    }
    pending_attempts = ticket.ai_attempts
    pending_next_attempt = ticket.ai_next_attempt_at
    pending_error = clear_terminal_ai_policy_errors(ticket.ai_error, {"route"})
    _deactivate_artifacts(ticket, {"route"})
    ticket.ai_suggested_team = None
    ticket.ai_secondary_team = None
    ticket.ai_routing_confidence = None
    ticket.ai_business_context = None
    ticket.ai_routing_scope = None
    ticket.ai_affected_service = None
    ticket.ai_failure_domain = None
    ticket.ai_routing_reason = None
    ticket.ai_routing_input_hash = None
    ticket.ai_source_hash = None
    ticket.ai_status = "queued" if pending_artifacts else "partial"
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_attempts = pending_attempts if pending_artifacts else 0
    ticket.ai_next_attempt_at = pending_next_attempt if pending_artifacts else None
    ticket.ai_requested_artifacts = (
        ",".join(sorted(pending_artifacts)) if pending_artifacts else None
    )
    ticket.ai_started_at = None
    ticket.ai_error = pending_error
