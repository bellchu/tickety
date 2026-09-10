"""Add the parallel chunked hybrid RAG v2 store.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-09
"""

from __future__ import annotations

import os
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _configured_dimensions() -> int:
    raw = (os.getenv("TICKET_EMBEDDING_DIMENSIONS") or "1536").strip()
    try:
        dimensions = int(raw)
    except ValueError as exc:
        raise RuntimeError("TICKET_EMBEDDING_DIMENSIONS must be an integer") from exc
    if not 1 <= dimensions <= 4096:
        raise RuntimeError("TICKET_EMBEDDING_DIMENSIONS must be between 1 and 4096")
    return dimensions


def _preflight_dimensions(bind, configured: int) -> int:
    relation = bind.execute(
        sa.text("SELECT to_regclass('ticket_search_documents')")
    ).scalar()
    if relation is None:
        # Fresh Alembic installations never passed through the historical
        # development bootstrap that created v1. Create the compatibility
        # table here so fresh production installs and upgrades share one
        # explicit dimension contract.
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        bind.execute(sa.text(f"""
            CREATE TABLE ticket_search_documents (
                id BIGSERIAL PRIMARY KEY,
                source_type VARCHAR NOT NULL,
                source_id VARCHAR NOT NULL,
                ticket_id VARCHAR,
                title TEXT DEFAULT '',
                body TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{{}}',
                content_hash VARCHAR NOT NULL,
                embedding vector({configured}),
                embedding_model VARCHAR,
                embedded_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source_type, source_id)
            )
        """))
        bind.execute(sa.text(
            "CREATE INDEX ix_ticket_search_documents_ticket_id "
            "ON ticket_search_documents (ticket_id)"
        ))
        bind.execute(sa.text(
            "CREATE INDEX ix_ticket_search_documents_source "
            "ON ticket_search_documents (source_type, source_id)"
        ))
        bind.execute(sa.text(
            "CREATE INDEX ix_ticket_search_documents_fts "
            "ON ticket_search_documents USING GIN ("
            "to_tsvector('simple'::regconfig, "
            "COALESCE(title, '') || ' ' || LEFT(COALESCE(body, ''), 20000)))"
        ))
        bind.execute(sa.text(
            "CREATE INDEX ix_ticket_search_documents_embedding "
            "ON ticket_search_documents USING hnsw (embedding vector_cosine_ops)"
        ))
        return configured

    embedding_type = bind.execute(sa.text("""
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute AS a
        WHERE a.attrelid = to_regclass('ticket_search_documents')
          AND a.attname = 'embedding'
          AND NOT a.attisdropped
    """)).scalar()
    match = re.fullmatch(r"vector\((\d+)\)", str(embedding_type or ""))
    if not match:
        raise RuntimeError(
            "ticket_search_documents.embedding is absent or is not a fixed vector"
        )
    existing = int(match.group(1))
    if existing != configured:
        raise RuntimeError(
            "TICKET_EMBEDDING_DIMENSIONS does not match the existing v1 vector column"
        )
    return existing


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # RAG v2 is PostgreSQL/pgvector-specific. SQLite remains a supported
        # demo and unit-test database and keeps using the core-table fallback.
        return

    dimensions = _preflight_dimensions(bind, _configured_dimensions())
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(sa.text("""
        CREATE TABLE rag_v2_schema_meta (
            key VARCHAR(80) PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(f"""
        CREATE TABLE ticket_search_chunks_v2 (
            chunk_id CHAR(64) PRIMARY KEY,
            scope_key VARCHAR(160) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            source_id VARCHAR(255) NOT NULL,
            ticket_id VARCHAR(255),
            chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
            section_path VARCHAR(500),
            content TEXT NOT NULL CHECK (char_length(content) <= 50000),
            content_hash CHAR(64) NOT NULL,
            parent_hash CHAR(64) NOT NULL,
            source_revision VARCHAR(128) NOT NULL,
            chunker_identity VARCHAR(80) NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding vector({dimensions}),
            embedding_identity VARCHAR(160),
            embedded_at TIMESTAMP,
            embedding_state VARCHAR(16) NOT NULL DEFAULT 'queued'
                CHECK (embedding_state IN ('queued', 'running', 'ready', 'dead_letter')),
            embedding_attempts INTEGER NOT NULL DEFAULT 0 CHECK (embedding_attempts >= 0),
            not_before TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            lease_id VARCHAR(36),
            lease_owner VARCHAR(128),
            lease_expires_at TIMESTAMP,
            last_error_code VARCHAR(80),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (scope_key, source_type, source_id, parent_hash, chunk_index)
        )
    """))
    op.execute(sa.text("""
        CREATE INDEX ix_ticket_search_chunks_v2_fts
        ON ticket_search_chunks_v2 USING GIN (
            to_tsvector(
                'simple'::regconfig,
                COALESCE(section_path, '') || ' ' || COALESCE(content, '')
            )
        )
    """))
    op.execute(sa.text("""
        CREATE INDEX ix_ticket_search_chunks_v2_embedding
        ON ticket_search_chunks_v2 USING hnsw (embedding vector_cosine_ops)
    """))
    op.create_index(
        "ix_ticket_search_chunks_v2_source",
        "ticket_search_chunks_v2",
        ["scope_key", "source_type", "source_id"],
    )
    op.create_index(
        "ix_ticket_search_chunks_v2_ticket_id",
        "ticket_search_chunks_v2",
        ["ticket_id"],
    )
    op.create_index(
        "ix_ticket_search_chunks_v2_identity",
        "ticket_search_chunks_v2",
        ["scope_key", "embedding_identity"],
    )
    op.execute(sa.text("""
        CREATE INDEX ix_ticket_search_chunks_v2_queue
        ON ticket_search_chunks_v2 (not_before, updated_at)
        WHERE embedding_state = 'queued'
    """))
    op.execute(sa.text("""
        CREATE INDEX ix_ticket_search_chunks_v2_expired_lease
        ON ticket_search_chunks_v2 (lease_expires_at)
        WHERE embedding_state = 'running'
    """))

    op.execute(sa.text(f"""
        CREATE TABLE rag_query_embedding_cache_v2 (
            scope_key VARCHAR(160) NOT NULL,
            query_hash CHAR(64) NOT NULL,
            embedding_identity VARCHAR(160) NOT NULL,
            dimensions INTEGER NOT NULL CHECK (dimensions > 0),
            embedding vector({dimensions}) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            hit_count BIGINT NOT NULL DEFAULT 0,
            PRIMARY KEY (scope_key, query_hash, embedding_identity, dimensions)
        )
    """))
    op.create_index(
        "ix_rag_query_embedding_cache_v2_expiry",
        "rag_query_embedding_cache_v2",
        ["expires_at"],
    )

    op.execute(sa.text("""
        CREATE TABLE rag_corpus_generations_v2 (
            scope_key VARCHAR(160) PRIMARY KEY,
            generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text("""
        CREATE TABLE rag_context_snapshots_v2 (
            id VARCHAR(36) PRIMARY KEY,
            ai_job_id VARCHAR(64),
            scope_key VARCHAR(160) NOT NULL,
            actor_id VARCHAR(255) NOT NULL,
            auth_fingerprint CHAR(64) NOT NULL,
            corpus_generation BIGINT NOT NULL,
            embedding_identity VARCHAR(160) NOT NULL,
            query_hash CHAR(64) NOT NULL,
            evidence_json JSONB NOT NULL,
            chunk_manifest_json JSONB NOT NULL,
            citation_allowlist_json JSONB NOT NULL,
            digest CHAR(64) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        )
    """))
    op.create_index(
        "ix_rag_context_snapshots_v2_expiry",
        "rag_context_snapshots_v2",
        ["expires_at"],
    )
    op.create_index(
        "ix_rag_context_snapshots_v2_job",
        "rag_context_snapshots_v2",
        ["ai_job_id"],
    )

    op.execute(sa.text("""
        INSERT INTO rag_v2_schema_meta (key, value)
        VALUES
            ('dimensions', :dimensions),
            ('chunker_identity', 'rag-v2-cl100k-450-50'),
            ('schema_version', '2')
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
    """).bindparams(dimensions=str(dimensions)))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; disable RAG v2 reads and apply a forward fix."
    )
