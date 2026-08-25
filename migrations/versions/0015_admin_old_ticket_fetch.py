"""Make old-ticket discovery an explicit admin-requested range.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sync_state", sa.Column("history_since_at", sa.DateTime(), nullable=True))
    op.add_column("sync_state", sa.Column("history_until_at", sa.DateTime(), nullable=True))
    op.add_column("sync_state", sa.Column("history_requested_at", sa.DateTime(), nullable=True))
    op.add_column("sync_state", sa.Column("history_requested_by", sa.String(length=255), nullable=True))

    # Existing history cursors came from the former automatic full-inventory
    # lane. Leaving the request timestamp empty ensures deployment cannot
    # resume those provider calls without a new authenticated admin action.
    op.execute(
        "UPDATE sync_state SET history_complete = TRUE "
        "WHERE history_requested_at IS NULL"
    )
    op.execute(
        "UPDATE sync_state SET recent_since_at = NULL, "
        "recent_cycle_started_at = NULL, recent_page = 1, "
        "recent_workspace_index = 0"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
