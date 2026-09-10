"""Allow decided change approvals to survive account purge anonymously.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("change_approvals", schema=None) as batch_op:
        batch_op.alter_column(
            "approver_id",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
