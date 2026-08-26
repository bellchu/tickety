"""Shared eligibility rules for automatic ticket intelligence."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import inspect, or_
from sqlalchemy.orm import Session

from .database import TicketRecord, TicketStatusConfigRecord
from .portable_keys import portable_ascii_lower, portable_ascii_lower_expression


DEFAULT_TERMINAL_STATUSES = frozenset({"closed", "resolved", "cancelled"})
AI_TERMINAL_LIFECYCLE = "not_applicable"
AI_COMPLETED_STATUSES = frozenset({"completed", "triage_completed"})
_SESSION_TERMINAL_CACHE_KEY = "tickety_ai_terminal_statuses"


def terminal_status_names(db: Session) -> set[str]:
    """Return configured terminal ticket states with a safe default."""
    cached = db.info.get(_SESSION_TERMINAL_CACHE_KEY)
    if cached is not None:
        return set(cached)
    if not inspect(db.connection()).has_table(TicketStatusConfigRecord.__tablename__):
        names = set(DEFAULT_TERMINAL_STATUSES)
        db.info[_SESSION_TERMINAL_CACHE_KEY] = frozenset(names)
        return names
    configured = db.query(TicketStatusConfigRecord.name).filter(
        TicketStatusConfigRecord.is_terminal.is_(True)
    ).all()
    names = set(DEFAULT_TERMINAL_STATUSES)
    names.update({
        portable_ascii_lower(row[0])
        for row in configured
        if row and str(row[0] or "").strip()
    })
    db.info[_SESSION_TERMINAL_CACHE_KEY] = frozenset(names)
    return names


def active_ticket_filter(db: Session):
    """SQL expression selecting tickets eligible for active work."""
    terminal = tuple(sorted(terminal_status_names(db)))
    return or_(
        TicketRecord.status.is_(None),
        portable_ascii_lower_expression(TicketRecord.status).notin_(terminal),
    )


def terminal_ticket_filter(db: Session):
    """SQL expression selecting tickets excluded from automatic AI."""
    terminal = tuple(sorted(terminal_status_names(db)))
    return portable_ascii_lower_expression(TicketRecord.status).in_(terminal)


def is_terminal_status(db: Session, status: Optional[str]) -> bool:
    return bool(
        status
        and portable_ascii_lower(status) in terminal_status_names(db)
    )


def ticket_is_terminal(db: Session, ticket: TicketRecord) -> bool:
    return is_terminal_status(db, ticket.status)


def mark_terminal_ai_not_applicable(ticket: TicketRecord) -> bool:
    """Cancel pending work for a terminal ticket without erasing artifacts."""
    if (ticket.ai_status or "").strip().lower() in AI_COMPLETED_STATUSES:
        return False
    changed = any((
        ticket.ai_status != AI_TERMINAL_LIFECYCLE,
        ticket.ai_claim_id is not None,
        ticket.ai_lease_expires_at is not None,
        ticket.ai_started_at is not None,
        ticket.ai_next_attempt_at is not None,
        ticket.ai_requested_artifacts is not None,
        ticket.ai_error != "terminal_ticket",
    ))
    ticket.ai_status = AI_TERMINAL_LIFECYCLE
    ticket.ai_claim_id = None
    ticket.ai_lease_expires_at = None
    ticket.ai_started_at = None
    ticket.ai_next_attempt_at = None
    ticket.ai_requested_artifacts = None
    ticket.ai_attempts = 0
    ticket.ai_error = "terminal_ticket"
    return changed
