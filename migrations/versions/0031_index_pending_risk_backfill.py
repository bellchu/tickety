"""Index pending escalation-risk backfill rows safely.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "ix_tickets_escalation_risk_backfill_pending"
_PREDICATE = sa.text(
    "ai_reasoning IS NOT NULL AND escalation_risk_backfilled_at IS NULL"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # This revision contains only the concurrent index operation. If an
        # interrupted build leaves an INVALID index while the database remains
        # stamped at 0030, a retry first removes that artifact and is safe.
        with op.get_context().autocommit_block():
            op.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS "{_INDEX_NAME}"'))
            op.create_index(
                _INDEX_NAME,
                "tickets",
                ["updated_at", "id"],
                unique=False,
                postgresql_where=_PREDICATE,
                postgresql_concurrently=True,
            )
    else:
        existing_indexes = {
            index["name"] for index in sa.inspect(bind).get_indexes("tickets")
        }
        if _INDEX_NAME not in existing_indexes:
            op.create_index(
                _INDEX_NAME,
                "tickets",
                ["updated_at", "id"],
                unique=False,
                sqlite_where=_PREDICATE,
            )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
