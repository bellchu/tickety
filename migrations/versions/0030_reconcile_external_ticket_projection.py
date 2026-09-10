"""Reconcile provider-owned ticket resolution and SLA projections.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tickets = sa.table(
        "tickets",
        sa.column("external_id", sa.String()),
        sa.column("external_source", sa.String()),
        sa.column("external_status", sa.String()),
        sa.column("external_due_by", sa.DateTime()),
        sa.column("external_fr_due_by", sa.DateTime()),
        sa.column("due_by", sa.DateTime()),
        sa.column("resolution_due_at", sa.DateTime()),
        sa.column("response_due_at", sa.DateTime()),
        sa.column("resolved_at", sa.DateTime()),
    )
    bind.execute(
        tickets.update().where(
            tickets.c.external_id.is_not(None),
            tickets.c.external_source.is_not(None),
            sa.or_(
                tickets.c.due_by.is_distinct_from(tickets.c.external_due_by),
                tickets.c.resolution_due_at.is_distinct_from(
                    tickets.c.external_due_by
                ),
                tickets.c.response_due_at.is_distinct_from(
                    tickets.c.external_fr_due_by
                ),
            ),
        ).values(
            due_by=tickets.c.external_due_by,
            resolution_due_at=tickets.c.external_due_by,
            response_due_at=tickets.c.external_fr_due_by,
        )
    )
    bind.execute(sa.text(
        "UPDATE tickets SET resolved_at = NULL "
        "WHERE external_id IS NOT NULL AND external_source IS NOT NULL "
        "AND external_status IS NOT NULL "
        "AND LOWER(TRIM(external_status)) NOT IN ('closed', 'resolved') "
        "AND resolved_at IS NOT NULL"
    ))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
