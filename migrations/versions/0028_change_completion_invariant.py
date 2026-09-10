"""Enforce canonical change lifecycle and completion metadata.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_COMPLETION_CHECK = (
    "status IN ('Draft', 'Submitted', 'CAB Review', 'Approved', "
    "'In Progress', 'Completed', 'Rejected', 'Cancelled') AND "
    "((status = 'Completed' AND completed_at IS NOT NULL) OR "
    "(status <> 'Completed' AND completed_at IS NULL))"
)


def upgrade() -> None:
    bind = op.get_bind()
    invalid_rows = bind.execute(sa.text(
        "SELECT id, status, completed_at FROM changes WHERE "
        "status IS NULL OR "
        "status NOT IN ('Draft', 'Submitted', 'CAB Review', 'Approved', "
        "'In Progress', 'Completed', 'Rejected', 'Cancelled') OR "
        "(status = 'Completed' AND completed_at IS NULL) OR "
        "(status <> 'Completed' AND completed_at IS NOT NULL) "
        "ORDER BY id LIMIT 20"
    )).mappings().all()
    if invalid_rows:
        samples = ", ".join(
            f"{row['id']!r} (status={row['status']!r}, "
            f"completed_at={row['completed_at']!r})"
            for row in invalid_rows
        )
        raise RuntimeError(
            "Cannot enforce the change lifecycle invariant until invalid rows "
            f"are repaired: {samples}"
        )

    with op.batch_alter_table("changes", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(),
            existing_nullable=True,
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_changes_status_completion",
            _STATUS_COMPLETION_CHECK,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
