"""Shared AI artifact lifecycle helpers."""

from sqlalchemy.orm import object_session


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
    ticket.category = None
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
