"""Shared AI artifact lifecycle helpers."""

from sqlalchemy import or_
from sqlalchemy.orm import object_session


_TERMINAL_POLICY_ERROR_SUFFIX = ":content_filtered"


def has_terminal_ai_policy_outcome(ticket) -> bool:
    """Whether the current ticket input reached a terminal provider policy result."""
    return any(
        item.strip().endswith(_TERMINAL_POLICY_ERROR_SUFFIX)
        for item in (ticket.ai_error or "").split(",")
    )


def automatic_ai_policy_eligible_filter():
    """Exclude terminal policy outcomes from automatic admission queries.

    Explicit retries clear ``ai_error`` before queueing, while source-input
    invalidation also clears it. The exclusion therefore applies only to an
    unchanged input version and cannot permanently strand an updated ticket.
    """
    from .database import TicketRecord

    return or_(
        TicketRecord.ai_error.is_(None),
        ~TicketRecord.ai_error.contains(_TERMINAL_POLICY_ERROR_SUFFIX),
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
    _deactivate_artifacts(ticket, {"triage", "summary", "resolution"})
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


def invalidate_ticket_resolution(ticket) -> None:
    """Invalidate downstream guidance while preserving valid triage artifacts."""
    _deactivate_artifacts(ticket, {"resolution"})
    ticket.recommended_solution = None
    ticket.ai_source_hash = None
    ticket.ai_status = "partial"
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_generated_at = None
    ticket.ai_error = None
