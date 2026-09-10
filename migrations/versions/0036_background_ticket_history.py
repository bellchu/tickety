"""Add an automatic background cursor for historical ticket discovery.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "background_history_page",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ))
        batch_op.add_column(sa.Column(
            "background_history_workspace_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "background_history_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column(
            "background_history_processed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "background_history_started_at",
            sa.DateTime(),
            nullable=True,
        ))
        batch_op.add_column(sa.Column(
            "background_history_through_at",
            sa.DateTime(),
            nullable=True,
        ))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
