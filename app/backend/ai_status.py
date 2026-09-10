"""Prompt-free operational summaries for durable AI ticket work."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from .ai_eligibility import active_ticket_filter
from .database import TicketRecord


@dataclass(frozen=True)
class AIQueueMetrics:
    total_tickets: int
    not_analyzed: int
    not_applicable: int
    queued: int
    queued_ready: int
    retry_scheduled: int
    running: int
    running_active: int
    lease_expired: int
    completed: int
    partial: int
    stale: int
    failed: int
    dead_letter: int
    paused: int
    oldest_queued_at: Optional[datetime]

    @property
    def attention(self) -> int:
        return sum((
            self.partial,
            self.stale,
            self.failed,
            self.dead_letter,
            self.paused,
            self.lease_expired,
        ))


def load_ai_queue_metrics(
    db: Session,
    now: datetime,
    *,
    operator_cleared_error: str,
) -> AIQueueMetrics:
    """Compute every queue counter in one scan of the ticket relation."""
    active_ticket = active_ticket_filter(db)
    queue_rows = db.query(
        TicketRecord.id.label("id"),
        TicketRecord.ai_status.label("ai_status"),
        TicketRecord.ai_error.label("ai_error"),
        TicketRecord.ai_next_attempt_at.label("ai_next_attempt_at"),
        TicketRecord.ai_lease_expires_at.label("ai_lease_expires_at"),
        TicketRecord.updated_at.label("updated_at"),
        case((active_ticket, True), else_=False).label("is_active"),
    ).subquery()
    queue = queue_rows.c
    is_active = queue.is_active.is_(True)
    normalized_status = func.lower(func.coalesce(queue.ai_status, "not_analyzed"))

    def count_if(predicate, label: str):
        return func.coalesce(
            func.sum(case((predicate, 1), else_=0)), 0
        ).label(label)

    summary = db.query(
        func.count(queue.id).label("total_tickets"),
        count_if(and_(
            is_active,
            queue.ai_status == "queued",
            or_(
                queue.ai_next_attempt_at.is_(None),
                queue.ai_next_attempt_at <= now,
            ),
        ), "queued_ready"),
        count_if(and_(
            is_active,
            queue.ai_status == "queued",
            queue.ai_next_attempt_at > now,
        ), "retry_scheduled"),
        count_if(and_(
            is_active,
            queue.ai_status == "running",
            queue.ai_lease_expires_at >= now,
        ), "running_active"),
        count_if(and_(
            is_active,
            queue.ai_status == "running",
            or_(
                queue.ai_lease_expires_at.is_(None),
                queue.ai_lease_expires_at < now,
            ),
        ), "lease_expired"),
        func.min(case((and_(
            is_active,
            queue.ai_status == "queued",
        ), queue.updated_at), else_=None)).label("oldest_queued_at"),
        count_if(
            normalized_status.in_(("completed", "triage_completed")),
            "completed",
        ),
        count_if(and_(is_active, queue.ai_status.is_(None)), "not_analyzed"),
        count_if(and_(is_active, queue.ai_status == "queued"), "queued"),
        count_if(and_(is_active, queue.ai_status == "running"), "running"),
        count_if(and_(
            queue.is_active.is_(False),
            or_(
                queue.ai_status.is_(None),
                queue.ai_status.notin_(("completed", "triage_completed")),
            ),
        ), "not_applicable"),
        count_if(and_(is_active, queue.ai_status == "partial"), "partial"),
        count_if(and_(
            is_active,
            queue.ai_status.in_(("stale", "legacy_stale", "provenance_unknown")),
        ), "stale"),
        count_if(and_(is_active, queue.ai_status == "failed"), "failed"),
        count_if(and_(is_active, queue.ai_status == "dead_letter"), "dead_letter"),
        count_if(and_(
            is_active,
            queue.ai_status == "paused",
            func.coalesce(queue.ai_error, "") != operator_cleared_error,
        ), "paused"),
    ).one()

    return AIQueueMetrics(
        total_tickets=int(summary.total_tickets or 0),
        not_analyzed=int(summary.not_analyzed or 0),
        not_applicable=int(summary.not_applicable or 0),
        queued=int(summary.queued or 0),
        queued_ready=int(summary.queued_ready or 0),
        retry_scheduled=int(summary.retry_scheduled or 0),
        running=int(summary.running or 0),
        running_active=int(summary.running_active or 0),
        lease_expired=int(summary.lease_expired or 0),
        completed=int(summary.completed or 0),
        partial=int(summary.partial or 0),
        stale=int(summary.stale or 0),
        failed=int(summary.failed or 0),
        dead_letter=int(summary.dead_letter or 0),
        paused=int(summary.paused or 0),
        oldest_queued_at=summary.oldest_queued_at,
    )
