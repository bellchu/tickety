"""Persist structured AI resolver-group routing results.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ROUTING_COLUMNS = (
    sa.Column("ai_secondary_team", sa.String(), nullable=True),
    sa.Column("ai_routing_confidence", sa.Float(), nullable=True),
    sa.Column("ai_business_context", sa.String(), nullable=True),
    sa.Column("ai_routing_scope", sa.String(), nullable=True),
    sa.Column("ai_affected_service", sa.String(), nullable=True),
    sa.Column("ai_failure_domain", sa.String(), nullable=True),
    sa.Column("ai_routing_reason", sa.Text(), nullable=True),
    sa.Column("ai_routing_input_hash", sa.String(length=64), nullable=True),
)


def upgrade() -> None:
    bind = op.get_bind()
    # Development bootstrap may already have added forward-compatible columns.
    # Keep the authoritative migration safe for that compatible schema.
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("tickets")
    }
    for column in _ROUTING_COLUMNS:
        if column.name not in existing_columns:
            op.add_column("tickets", column)
    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("tickets")
    }
    if "ix_tickets_ai_routing_input_hash" not in existing_indexes:
        op.create_index(
            "ix_tickets_ai_routing_input_hash",
            "tickets",
            ["ai_routing_input_hash"],
            unique=False,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
