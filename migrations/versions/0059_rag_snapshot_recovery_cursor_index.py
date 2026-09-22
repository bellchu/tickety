"""Index monotonic RAG snapshot recovery pages.

Revision ID: 0059
Revises: 0058
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if "rag_context_snapshots_v2" not in inspector.get_table_names():
        raise RuntimeError("RAG snapshots are missing; restore a verified backup")
    op.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_rag_context_snapshots_v2_created_id
        ON rag_context_snapshots_v2 (created_at, id)
    """))


def downgrade() -> None:
    raise RuntimeError("Tickety migrations are forward-only; apply a forward repair")
