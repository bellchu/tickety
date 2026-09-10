"""Add durable, rate-aware Freshservice sync progress.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("external_conversations_synced_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_tickets_external_conversations_synced_at",
        "tickets",
        ["external_conversations_synced_at"],
    )

    columns = (
        sa.Column("recent_since_at", sa.DateTime(), nullable=True),
        sa.Column("recent_cycle_started_at", sa.DateTime(), nullable=True),
        sa.Column("recent_page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recent_workspace_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent_completed_at", sa.DateTime(), nullable=True),
        sa.Column("history_page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("history_workspace_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("history_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("history_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversations_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_token", sa.String(length=36), nullable=True),
        sa.Column("run_started_at", sa.DateTime(), nullable=True),
        sa.Column("run_finished_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("rate_limit_total", sa.Integer(), nullable=True),
        sa.Column("rate_limit_remaining", sa.Integer(), nullable=True),
        sa.Column("rate_limit_used", sa.Integer(), nullable=True),
        sa.Column("last_batch_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_batch_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_batch_errors", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in columns:
        op.add_column("sync_state", column)
    op.create_index("ix_sync_state_run_token", "sync_state", ["run_token"])
    op.create_index("ix_sync_state_next_retry_at", "sync_state", ["next_retry_at"])


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
