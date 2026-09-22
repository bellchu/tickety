"""Index RAG snapshot ownership by authoritative source.

Revision ID: 0058
Revises: 0057
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels = None
depends_on = None


_SNAPSHOTS = "rag_context_snapshots_v2"
_REFERENCES = "rag_context_snapshot_sources_v2"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if _SNAPSHOTS not in inspector.get_table_names():
        raise RuntimeError("RAG snapshots are missing; restore a verified backup")
    if _REFERENCES not in inspector.get_table_names():
        op.execute(sa.text("""
            CREATE TABLE rag_context_snapshot_sources_v2 (
                snapshot_id VARCHAR(36) NOT NULL REFERENCES rag_context_snapshots_v2(id)
                    ON DELETE CASCADE,
                source_type VARCHAR(32) NOT NULL,
                source_id VARCHAR(255) NOT NULL,
                PRIMARY KEY (snapshot_id, source_type, source_id)
            )
        """))
    op.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_rag_context_snapshot_sources_v2_source
        ON rag_context_snapshot_sources_v2 (source_type, source_id, snapshot_id)
    """))

    # A legacy snapshot is safe to retain only when its module-owned manifest
    # is a non-empty array of complete string source references.  Privacy wins
    # over availability: malformed or partially mappable evidence is removed.
    op.execute(sa.text("""
        DELETE FROM rag_context_snapshots_v2 AS snapshot
        -- PostgreSQL is free to reorder boolean predicates.  Keep all array
        -- functions inside CASE so a malformed object/scalar manifest is
        -- deleted rather than making this privacy-first migration abort.
        WHERE CASE
            WHEN jsonb_typeof(snapshot.chunk_manifest_json) IS DISTINCT FROM 'array' THEN true
            WHEN jsonb_array_length(snapshot.chunk_manifest_json) = 0 THEN true
            ELSE EXISTS (
                SELECT 1
                FROM jsonb_array_elements(snapshot.chunk_manifest_json) AS item(value)
                WHERE jsonb_typeof(item.value) <> 'object'
                   OR jsonb_typeof(item.value->'source_type') <> 'string'
                   OR jsonb_typeof(item.value->'source_id') <> 'string'
                   OR btrim(item.value->>'source_type') = ''
                   OR btrim(item.value->>'source_id') = ''
                   OR item.value->>'source_type' NOT IN ('ticket', 'comment', 'kb_article')
                   OR length(item.value->>'source_type') > 32
                   OR length(item.value->>'source_id') > 255
            )
        END
    """))
    op.execute(sa.text("""
        INSERT INTO rag_context_snapshot_sources_v2 (
            snapshot_id, source_type, source_id
        )
        SELECT DISTINCT snapshot.id,
               item.value->>'source_type', item.value->>'source_id'
        FROM rag_context_snapshots_v2 AS snapshot
        CROSS JOIN LATERAL jsonb_array_elements(snapshot.chunk_manifest_json) AS item(value)
        ON CONFLICT (snapshot_id, source_type, source_id) DO NOTHING
    """))
    # Existing rows in a partially applied/previously failed migration must
    # never leave a snapshot without an indexed ownership reference.
    op.execute(sa.text("""
        DELETE FROM rag_context_snapshots_v2 AS snapshot
        WHERE NOT EXISTS (
            SELECT 1
            FROM rag_context_snapshot_sources_v2 AS reference
            WHERE reference.snapshot_id = snapshot.id
        )
    """))


def downgrade() -> None:
    raise RuntimeError("Tickety migrations are forward-only; apply a forward repair")
