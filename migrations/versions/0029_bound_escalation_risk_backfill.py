"""Bound the one-time escalation-risk backfill.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Demo databases can receive forward-compatible columns from init_db()
    # before Alembic is advanced. Keep the authoritative migration safe to
    # apply to that already-compatible schema.
    ticket_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("tickets")
    }
    if "escalation_risk_backfilled_at" not in ticket_columns:
        op.add_column(
            "tickets",
            sa.Column("escalation_risk_backfilled_at", sa.DateTime(), nullable=True),
        )
    bind.execute(sa.text(
        "UPDATE tickets SET escalation_risk_backfilled_at = "
        "COALESCE(ai_generated_at, updated_at, created_at, CURRENT_TIMESTAMP) "
        "WHERE escalation_risk_backfilled_at IS NULL "
        "AND ai_reasoning IS NOT NULL "
        "AND escalation_risk IS NOT NULL AND escalation_risk <> 0"
    ))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
