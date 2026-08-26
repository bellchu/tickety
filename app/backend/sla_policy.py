"""Shared SLA eligibility policy for ticket clocks and aggregates."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, func

from .database import TicketRecord
from .portable_keys import portable_ascii_lower, portable_ascii_lower_expression


# Freshservice projects status 3 as ``Pending``; operationally that is its
# built-in on-hold state. Keep aliases here so every SLA surface applies the
# same rule even when another provider uses spaces, hyphens, or underscores.
DEFAULT_SLA_EXEMPT_STATUSES = frozenset({
    "closed",
    "resolved",
    "cancelled",
    "canceled",
    "completed",
    "paused",
    "pending",
    "on hold",
})


def normalize_sla_status(value: object) -> str:
    return portable_ascii_lower(
        str(value or "").replace("_", " ").replace("-", " ")
    )


def sla_exempt_status_names(additional_statuses: Iterable[str] = ()) -> set[str]:
    return {
        normalize_sla_status(value)
        for value in (*DEFAULT_SLA_EXEMPT_STATUSES, *additional_statuses)
        if normalize_sla_status(value)
    }


def ticket_is_sla_exempt(
    ticket: TicketRecord,
    additional_statuses: Iterable[str] = (),
) -> bool:
    if ticket.sla_paused_at is not None:
        return True
    exempt = sla_exempt_status_names(additional_statuses)
    return any(
        normalize_sla_status(value) in exempt
        for value in (
            ticket.status,
            ticket.workflow_status,
            ticket.external_status,
        )
        if value
    )


def _normalized_status_expression(column):
    return portable_ascii_lower_expression(func.replace(func.replace(
        func.coalesce(column, ""), "_", " "
    ), "-", " "))


def sla_eligible_filter(additional_statuses: Iterable[str] = ()):
    """Return a SQL predicate selecting tickets with an active SLA clock."""
    exempt = tuple(sorted(sla_exempt_status_names(additional_statuses)))
    return and_(
        TicketRecord.sla_paused_at.is_(None),
        _normalized_status_expression(TicketRecord.status).notin_(exempt),
        _normalized_status_expression(TicketRecord.workflow_status).notin_(exempt),
        _normalized_status_expression(TicketRecord.external_status).notin_(exempt),
    )
