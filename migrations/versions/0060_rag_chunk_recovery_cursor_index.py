"""Index bounded RAG chunk eligibility recovery pages.

Revision ID: 0060
Revises: 0059
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if "ticket_search_chunks_v2" not in inspector.get_table_names():
        raise RuntimeError("RAG chunks are missing; restore a verified backup")
    # This exactly matches the scope-constrained keyset scan used by
    # ``purge_ineligible_chunks``.  The older source index ends at source_id,
    # which leaves PostgreSQL free to sort a large source group by chunk_id.
    op.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_ticket_search_chunks_v2_scope_source_chunk
        ON ticket_search_chunks_v2 (scope_key, source_type, source_id, chunk_id)
    """))


def downgrade() -> None:
    raise RuntimeError("Tickety migrations are forward-only; apply a forward repair")
