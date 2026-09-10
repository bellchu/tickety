"""Reopen background history with an exhaustive provider cursor.

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    actual_columns = {
        column["name"] for column in inspector.get_columns("sync_state")
    }
    if "background_history_scan_version" in actual_columns:
        # Historical demo bootstrap can create the exact forward-compatible
        # column from ORM metadata before Alembic reaches this revision.
        return
    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "background_history_scan_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
