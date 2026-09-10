from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import KbArticleRecord, TicketCommentRecord, TicketRecord
from .chunking import SourceTooLargeError, chunk_id, chunk_source, parent_hash
from .config import chunker_identity, dimensions, scope_key, write_enabled


_PORTAL_SOURCE = "portal"
_MAX_CHUNKS = {"ticket": 16, "comment": 8, "kb_article": 128}


@dataclass(frozen=True)
class SourceSnapshot:
    source_type: str
    source_id: str
    ticket_id: Optional[str]
    title: str
    body: str
    metadata: dict[str, Any]
    revision: str

    @property
    def parent_hash(self) -> str:
        return parent_hash(
            source_type=self.source_type,
            source_id=self.source_id,
            title=self.title,
            body=self.body,
            metadata=self.metadata,
        )


def _private_comment_indexing_enabled() -> bool:
    from ..ticket_vectors import private_comment_indexing_enabled

    return private_comment_indexing_enabled()


def _revision(value: Any, fallback: str) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if value is not None:
        return str(value)[:128]
    return fallback[:128]


def _ticket_metadata(ticket: TicketRecord) -> dict[str, Any]:
    return {
        "evidence_version": 2,
        "display_title": ticket.subject or "",
        "status": ticket.status,
        "workflow_status": ticket.workflow_status,
        "priority": ticket.priority,
        "category": ticket.category,
        "assignee_id": ticket.assignee_id,
        "ticket_type": ticket.ticket_type,
        "external_source": ticket.external_source,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "resolved_at": ticket.resolved_at,
        "tags": ticket.tags,
    }


def authoritative_source(
    db: Session,
    source_type: str,
    source_id: str,
    *,
    for_update: bool = False,
) -> Optional[SourceSnapshot]:
    """Read evidence and eligibility only from current authoritative tables."""
    if source_type == "ticket":
        query = db.query(TicketRecord).filter(TicketRecord.id == source_id)
        if for_update:
            query = query.populate_existing().with_for_update()
        ticket = query.first()
        if not ticket or str(ticket.external_source or "").strip().lower() == _PORTAL_SOURCE:
            return None
        metadata = _ticket_metadata(ticket)
        fallback = hashlib.sha256(
            f"{ticket.subject or ''}|{ticket.description or ''}".encode("utf-8")
        ).hexdigest()
        return SourceSnapshot(
            "ticket",
            str(ticket.id),
            str(ticket.id),
            ticket.subject or "",
            ticket.description or "",
            metadata,
            _revision(ticket.updated_at, fallback),
        )

    if source_type == "comment":
        try:
            numeric_id = int(source_id)
        except (TypeError, ValueError):
            return None
        query = db.query(TicketCommentRecord).filter(TicketCommentRecord.id == numeric_id)
        if for_update:
            query = query.populate_existing().with_for_update()
        comment = query.first()
        if not comment:
            return None
        ticket_query = db.query(TicketRecord).filter(TicketRecord.id == comment.ticket_id)
        if for_update:
            ticket_query = ticket_query.populate_existing().with_for_update()
        ticket = ticket_query.first()
        if (
            not ticket
            or str(ticket.external_source or "").strip().lower() == _PORTAL_SOURCE
            or (bool(comment.is_private) and not _private_comment_indexing_enabled())
        ):
            return None
        metadata = {
            "display_title": f"Ticket comment on {comment.ticket_id}",
            "is_private": bool(comment.is_private),
            "author_id": comment.author_id,
            "author_name": comment.author_name,
            "created_at": comment.created_at,
        }
        fallback = hashlib.sha256((comment.body or "").encode("utf-8")).hexdigest()
        return SourceSnapshot(
            "comment",
            str(comment.id),
            str(comment.ticket_id),
            f"Ticket comment on {comment.ticket_id}",
            comment.body or "",
            metadata,
            _revision(comment.created_at, fallback),
        )

    if source_type == "kb_article":
        query = db.query(KbArticleRecord).filter(KbArticleRecord.id == source_id)
        if for_update:
            query = query.populate_existing().with_for_update()
        article = query.first()
        if not article or not (
            article.status == "published"
            and article.reviewer_id
            and (article.author_id is None or article.reviewer_id != article.author_id)
        ):
            return None
        metadata = {
            "display_title": article.title or "",
            "slug": article.slug,
            "category": article.category,
            "tags": article.tags,
            "status": article.status,
            "author_id": article.author_id,
            "reviewer_id": article.reviewer_id,
            "updated_at": article.updated_at,
            "version": article.version,
        }
        fallback = hashlib.sha256(
            f"{article.title or ''}|{article.content or ''}|{article.version or 0}".encode("utf-8")
        ).hexdigest()
        return SourceSnapshot(
            "kb_article",
            str(article.id),
            None,
            article.title or "",
            article.content or "",
            metadata,
            _revision(article.updated_at, fallback),
        )
    return None


def store_ready(db: Session) -> bool:
    if getattr(getattr(db, "bind", None), "dialect", None) is None:
        return False
    if db.bind.dialect.name != "postgresql":
        return False
    try:
        row = db.execute(text("""
            SELECT to_regclass('ticket_search_chunks_v2') AS relation,
                   format_type(a.atttypid, a.atttypmod) AS embedding_type
            FROM pg_attribute AS a
            WHERE a.attrelid = to_regclass('ticket_search_chunks_v2')
              AND a.attname = 'embedding'
              AND NOT a.attisdropped
        """)).first()
        return bool(
            row
            and row.relation
            and str(row.embedding_type or "") == f"vector({dimensions()})"
        )
    except Exception:
        db.rollback()
        return False


def corpus_generation(db: Session, scope: str | None = None) -> int:
    scope = scope or scope_key()
    if not store_ready(db):
        return 0
    row = db.execute(text("""
        SELECT generation
        FROM rag_corpus_generations_v2
        WHERE scope_key = :scope_key
    """), {"scope_key": scope}).first()
    return int(row.generation if row else 0)


def _increment_generation(db: Session, scope: str) -> None:
    db.execute(text("""
        INSERT INTO rag_corpus_generations_v2 (scope_key, generation)
        VALUES (:scope_key, 1)
        ON CONFLICT (scope_key) DO UPDATE
        SET generation = rag_corpus_generations_v2.generation + 1,
            updated_at = CURRENT_TIMESTAMP
    """), {"scope_key": scope})


def _error_key(scope: str, source_type: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{scope}|{source_type}|{source_id}".encode("utf-8")).hexdigest()
    return f"index_error:{source_type[:16]}:{digest[:40]}"


def _record_index_error(
    db: Session, scope: str, source_type: str, source_id: str, code: str
) -> None:
    db.execute(text("""
        INSERT INTO rag_v2_schema_meta (key, value)
        VALUES (:key, :value)
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
    """), {"key": _error_key(scope, source_type, source_id), "value": code[:80]})


def _clear_index_error(db: Session, scope: str, source_type: str, source_id: str) -> None:
    db.execute(
        text("DELETE FROM rag_v2_schema_meta WHERE key = :key"),
        {"key": _error_key(scope, source_type, source_id)},
    )


def replace_source_chunks(
    db: Session,
    source_type: str,
    source_id: str,
    *,
    force: bool = False,
) -> bool:
    """Atomically replace one source's chunks without provider I/O."""
    if not write_enabled() or not store_ready(db):
        return False
    scope = scope_key()
    source = authoritative_source(db, source_type, str(source_id), for_update=True)
    existing = db.execute(text("""
        SELECT chunk_id, chunk_index, content_hash, parent_hash, chunker_identity
        FROM ticket_search_chunks_v2
        WHERE scope_key = :scope_key
          AND source_type = :source_type
          AND source_id = :source_id
        ORDER BY chunk_index
    """), {
        "scope_key": scope,
        "source_type": source_type,
        "source_id": str(source_id),
    }).all()
    if source is None:
        if existing:
            db.execute(text("""
                DELETE FROM ticket_search_chunks_v2
                WHERE scope_key = :scope_key
                  AND source_type = :source_type
                  AND source_id = :source_id
            """), {
                "scope_key": scope,
                "source_type": source_type,
                "source_id": str(source_id),
            })
            _increment_generation(db, scope)
            db.commit()
            return True
        db.rollback()
        return False

    identity = chunker_identity()
    current_parent_hash = source.parent_hash
    try:
        chunks = chunk_source(
            source.title,
            source.body,
            max_chunks=_MAX_CHUNKS[source_type],
        )
    except SourceTooLargeError:
        db.execute(text("""
            DELETE FROM ticket_search_chunks_v2
            WHERE scope_key = :scope_key
              AND source_type = :source_type
              AND source_id = :source_id
        """), {
            "scope_key": scope,
            "source_type": source_type,
            "source_id": str(source_id),
        })
        _record_index_error(db, scope, source_type, str(source_id), "source_too_large")
        if existing:
            _increment_generation(db, scope)
        db.commit()
        return False

    expected = [
        {
            "chunk_id": chunk_id(
                scope,
                source.source_type,
                source.source_id,
                current_parent_hash,
                chunk.index,
                identity,
            ),
            "chunk_index": chunk.index,
            "content_hash": chunk.content_hash,
        }
        for chunk in chunks
    ]
    expected_by_index = {item["chunk_index"]: item for item in expected}
    actual = {
        (
            str(row.chunk_id),
            int(row.chunk_index),
            str(row.content_hash),
            str(row.parent_hash),
            str(row.chunker_identity),
        )
        for row in existing
    }
    wanted = {
        (
            item["chunk_id"],
            item["chunk_index"],
            item["content_hash"],
            current_parent_hash,
            identity,
        )
        for item in expected
    }
    if not force and actual == wanted:
        db.rollback()
        return False

    db.execute(text("""
        DELETE FROM ticket_search_chunks_v2
        WHERE scope_key = :scope_key
          AND source_type = :source_type
          AND source_id = :source_id
    """), {
        "scope_key": scope,
        "source_type": source_type,
        "source_id": str(source_id),
    })
    metadata_json = json.dumps(
        source.metadata,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    if chunks:
        db.execute(text("""
            INSERT INTO ticket_search_chunks_v2 (
                chunk_id, scope_key, source_type, source_id, ticket_id,
                chunk_index, section_path, content, content_hash, parent_hash,
                source_revision, chunker_identity, metadata_json,
                embedding_state, embedding_attempts, not_before
            ) VALUES (
                :chunk_id, :scope_key, :source_type, :source_id, :ticket_id,
                :chunk_index, :section_path, :content, :content_hash, :parent_hash,
                :source_revision, :chunker_identity, CAST(:metadata_json AS jsonb),
                'queued', 0, CURRENT_TIMESTAMP
            )
        """), [
            {
                "chunk_id": expected_by_index[chunk.index]["chunk_id"],
                "scope_key": scope,
                "source_type": source.source_type,
                "source_id": source.source_id,
                "ticket_id": source.ticket_id,
                "chunk_index": chunk.index,
                "section_path": chunk.section_path,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "parent_hash": current_parent_hash,
                "source_revision": source.revision,
                "chunker_identity": identity,
                "metadata_json": metadata_json,
            }
            for chunk in chunks
        ])
    _clear_index_error(db, scope, source_type, str(source_id))
    _increment_generation(db, scope)
    db.commit()
    return True


def delete_source_chunks(db: Session, source_type: str, source_id: str) -> int:
    if not store_ready(db):
        return 0
    scope = scope_key()
    result = db.execute(text("""
        DELETE FROM ticket_search_chunks_v2
        WHERE scope_key = :scope_key
          AND source_type = :source_type
          AND source_id = :source_id
    """), {
        "scope_key": scope,
        "source_type": source_type,
        "source_id": str(source_id),
    })
    count = int(result.rowcount or 0)
    if count:
        _increment_generation(db, scope)
    db.commit()
    return count


def delete_ticket_chunks(db: Session, ticket_id: str, *, ticket_only: bool = False) -> int:
    if not store_ready(db):
        return 0
    scope = scope_key()
    source_filter = "AND source_type = 'ticket'" if ticket_only else ""
    result = db.execute(text(f"""
        DELETE FROM ticket_search_chunks_v2
        WHERE scope_key = :scope_key
          AND ticket_id = :ticket_id
          {source_filter}
    """), {"scope_key": scope, "ticket_id": str(ticket_id)})
    count = int(result.rowcount or 0)
    if count:
        _increment_generation(db, scope)
    db.commit()
    return count


def purge_ineligible_chunks(db: Session) -> int:
    """Remove evidence that current authoritative policy no longer admits."""
    if not store_ready(db):
        return 0
    scope = scope_key()
    result = db.execute(text("""
        DELETE FROM ticket_search_chunks_v2 AS chunk
        WHERE chunk.scope_key = :scope_key
          AND (
              (
                  chunk.source_type = 'ticket'
                  AND NOT EXISTS (
                      SELECT 1 FROM tickets AS ticket
                      WHERE ticket.id = chunk.source_id
                        AND LOWER(COALESCE(ticket.external_source, '')) <> 'portal'
                  )
              )
              OR (
                  chunk.source_type = 'comment'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ticket_comments AS comment
                      JOIN tickets AS ticket ON ticket.id = comment.ticket_id
                      WHERE CAST(comment.id AS text) = chunk.source_id
                        AND LOWER(COALESCE(ticket.external_source, '')) <> 'portal'
                        AND (
                            :include_private_comments
                            OR COALESCE(comment.is_private, false) = false
                        )
                  )
              )
              OR (
                  chunk.source_type = 'kb_article'
                  AND NOT EXISTS (
                      SELECT 1 FROM kb_articles AS article
                      WHERE article.id = chunk.source_id
                        AND article.status = 'published'
                        AND article.reviewer_id IS NOT NULL
                        AND (
                            article.author_id IS NULL
                            OR article.reviewer_id <> article.author_id
                        )
                  )
              )
          )
    """), {
        "scope_key": scope,
        "include_private_comments": _private_comment_indexing_enabled(),
    })
    count = int(result.rowcount or 0)
    if count:
        _increment_generation(db, scope)
    db.commit()
    return count


def has_ticket_source(db: Session, ticket_id: str) -> bool:
    if not store_ready(db):
        return False
    return db.execute(text("""
        SELECT 1
        FROM ticket_search_chunks_v2
        WHERE scope_key = :scope_key
          AND source_type = 'ticket'
          AND source_id = :source_id
        LIMIT 1
    """), {"scope_key": scope_key(), "source_id": str(ticket_id)}).first() is not None


def _ordered_sources(db: Session, model, ids: list[str], *, numeric: bool = False):
    if not ids:
        return []
    lookup_ids = [int(item) for item in ids] if numeric else ids
    rows = db.query(model).filter(model.id.in_(lookup_ids)).all()
    by_id = {str(row.id): row for row in rows}
    return [by_id[item] for item in ids if item in by_id]


def backfill_missing_chunks(
    db: Session,
    *,
    limit: int,
    include_comments: bool,
    include_kb: bool,
    force: bool = False,
) -> dict[str, int]:
    result = {
        "tickets_seen": 0,
        "comments_seen": 0,
        "kb_seen": 0,
        "sources_changed": 0,
    }
    if not write_enabled() or not store_ready(db):
        return result
    scope = scope_key()
    ticket_ids = [str(item) for item in db.execute(text("""
        SELECT ticket.id
        FROM tickets AS ticket
        LEFT JOIN ticket_search_chunks_v2 AS chunk
          ON chunk.scope_key = :scope_key
         AND chunk.source_type = 'ticket'
         AND chunk.source_id = ticket.id
        WHERE chunk.chunk_id IS NULL
          AND LOWER(COALESCE(ticket.external_source, '')) <> 'portal'
        ORDER BY ticket.updated_at DESC, ticket.id
        LIMIT :limit
    """), {"scope_key": scope, "limit": limit}).scalars().all()]
    for ticket in _ordered_sources(db, TicketRecord, ticket_ids):
        result["tickets_seen"] += 1
        if replace_source_chunks(db, "ticket", str(ticket.id), force=force):
            result["sources_changed"] += 1

    if include_comments:
        comment_ids = [str(item) for item in db.execute(text("""
            SELECT comment.id
            FROM ticket_comments AS comment
            JOIN tickets AS ticket ON ticket.id = comment.ticket_id
            LEFT JOIN ticket_search_chunks_v2 AS chunk
              ON chunk.scope_key = :scope_key
             AND chunk.source_type = 'comment'
             AND chunk.source_id = CAST(comment.id AS text)
            WHERE chunk.chunk_id IS NULL
              AND LOWER(COALESCE(ticket.external_source, '')) <> 'portal'
              AND (
                  :include_private_comments
                  OR COALESCE(comment.is_private, false) = false
              )
            ORDER BY comment.created_at DESC, comment.id
            LIMIT :limit
        """), {
            "scope_key": scope,
            "limit": limit,
            "include_private_comments": _private_comment_indexing_enabled(),
        }).scalars().all()]
        for comment in _ordered_sources(
            db, TicketCommentRecord, comment_ids, numeric=True
        ):
            result["comments_seen"] += 1
            if replace_source_chunks(db, "comment", str(comment.id), force=force):
                result["sources_changed"] += 1

    if include_kb:
        article_ids = [str(item) for item in db.execute(text("""
            SELECT article.id
            FROM kb_articles AS article
            LEFT JOIN ticket_search_chunks_v2 AS chunk
              ON chunk.scope_key = :scope_key
             AND chunk.source_type = 'kb_article'
             AND chunk.source_id = article.id
            WHERE chunk.chunk_id IS NULL
              AND article.status = 'published'
              AND article.reviewer_id IS NOT NULL
              AND (
                  article.author_id IS NULL
                  OR article.reviewer_id <> article.author_id
              )
            ORDER BY article.updated_at DESC, article.id
            LIMIT :limit
        """), {"scope_key": scope, "limit": limit}).scalars().all()]
        for article in _ordered_sources(db, KbArticleRecord, article_ids):
            result["kb_seen"] += 1
            if replace_source_chunks(db, "kb_article", str(article.id), force=force):
                result["sources_changed"] += 1
    return result


def status(db: Session) -> dict[str, Any]:
    ready = store_ready(db)
    result: dict[str, Any] = {
        "ready": ready,
        "read_enabled": False,
        "write_enabled": write_enabled(),
        "scope_key": scope_key(),
        "chunks": 0,
        "queued": 0,
        "running": 0,
        "ready_chunks": 0,
        "dead_letter": 0,
        "generation": 0,
        "indexing_errors": 0,
        "stale_identity_chunks": 0,
        "oldest_queue_age_seconds": 0,
        "query_cache_rows": 0,
        "query_cache_hits": 0,
        "active_snapshots": 0,
    }
    from .config import read_enabled

    result["read_enabled"] = read_enabled()
    if not ready:
        return result
    row = db.execute(text("""
        SELECT COUNT(*) AS chunks,
               COUNT(*) FILTER (WHERE embedding_state = 'queued') AS queued,
               COUNT(*) FILTER (WHERE embedding_state = 'running') AS running,
               COUNT(*) FILTER (WHERE embedding_state = 'ready') AS ready_chunks,
               COUNT(*) FILTER (WHERE embedding_state = 'dead_letter') AS dead_letter
        FROM ticket_search_chunks_v2
        WHERE scope_key = :scope_key
    """), {"scope_key": scope_key()}).first()
    if row:
        result.update({name: int(getattr(row, name) or 0) for name in (
            "chunks", "queued", "running", "ready_chunks", "dead_letter"
        )})
    result["generation"] = corpus_generation(db)
    result["indexing_errors"] = int(db.execute(text("""
        SELECT COUNT(*)
        FROM rag_v2_schema_meta
        WHERE key LIKE 'index_error:%'
    """)).scalar() or 0)
    from ..ticket_vectors import _embedding_identity

    metrics = db.execute(text("""
        SELECT
            COUNT(*) FILTER (
                WHERE embedding IS NOT NULL
                  AND embedding_identity IS DISTINCT FROM :embedding_identity
            ) AS stale_identity_chunks,
            COALESCE(MAX(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at))) FILTER (
                WHERE embedding_state = 'queued'
            ), 0) AS oldest_queue_age_seconds,
            (SELECT COUNT(*) FROM rag_query_embedding_cache_v2
             WHERE scope_key = :scope_key
               AND expires_at > CURRENT_TIMESTAMP) AS query_cache_rows,
            (SELECT COALESCE(SUM(hit_count), 0) FROM rag_query_embedding_cache_v2
             WHERE scope_key = :scope_key
               AND expires_at > CURRENT_TIMESTAMP) AS query_cache_hits,
            (SELECT COUNT(*) FROM rag_context_snapshots_v2
             WHERE scope_key = :scope_key
               AND expires_at > CURRENT_TIMESTAMP) AS active_snapshots
        FROM ticket_search_chunks_v2
        WHERE scope_key = :scope_key
    """), {
        "scope_key": scope_key(),
        "embedding_identity": _embedding_identity(),
    }).first()
    if metrics:
        for name in (
            "stale_identity_chunks",
            "oldest_queue_age_seconds",
            "query_cache_rows",
            "query_cache_hits",
            "active_snapshots",
        ):
            result[name] = int(float(getattr(metrics, name) or 0))
    return result
