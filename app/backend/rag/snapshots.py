from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .chunking import canonical_json
from .config import scope_key, snapshot_ttl_seconds
from .retrieval_v2 import query_hash
from .store_v2 import authoritative_source, corpus_generation, store_ready


_DEFAULT_RETENTION_BATCH = 500
# ``rag_v2_schema_meta.key`` is VARCHAR(80); leave room for a SHA-256 digest.
_PENDING_SOURCE_PURGE_PREFIX = "snapshot_purge:"
# A single durable cursor keeps the fallback eligibility recovery from starting
# at the beginning of the snapshot table on every retention interval.  The
# normal source-mutation queue is the prompt purge path; this is deliberately
# a bounded crash-recovery sweep.
_INELIGIBLE_SNAPSHOT_CURSOR_KEY = "snapshot_ineligible_cursor"


@dataclass(frozen=True)
class SourceSnapshotPurgeIntent:
    """One exact, durable source-revocation intent.

    The token is part of the stored value, rather than merely an in-process
    handle.  A drain can therefore delete only the mutation it observed; a
    newer mutation for the same source survives a concurrent older drain.
    """

    source_type: str
    source_id: str
    value: str


def _bounded_limit(value: int) -> int:
    """Keep maintenance work predictable even when called by a batch path."""
    return max(1, min(int(value), 5_000))


def _ineligible_snapshot_cursor(value: Any) -> tuple[datetime | None, str]:
    """Decode a fail-safe, forward-compatible eligibility sweep cursor."""
    payload = _json_object(value, dict)
    created_at = payload.get("created_at")
    snapshot_id = payload.get("id")
    if not isinstance(created_at, str) or not isinstance(snapshot_id, str):
        return None, ""
    try:
        decoded = datetime.fromisoformat(created_at)
    except ValueError:
        return None, ""
    # Database ``created_at`` is a timezone-naive TIMESTAMP.  Do not feed an
    # unexpected offset into the ordering predicate; restart safely instead.
    if decoded.tzinfo is not None or not snapshot_id:
        return None, ""
    return decoded, snapshot_id


def _delete_snapshot_ids(db: Session, snapshot_ids: Iterable[str]) -> int:
    ids = list(dict.fromkeys(str(item) for item in snapshot_ids if item))
    if not ids:
        return 0
    result = db.execute(text("""
        DELETE FROM rag_context_snapshots_v2
        WHERE id = ANY(:snapshot_ids)
    """), {"snapshot_ids": ids})
    return int(result.rowcount or 0)


def _source_pairs(sources: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted({
        (str(source_type), str(source_id))
        for source_type, source_id in sources
        if source_type and source_id is not None
    })


def prune_expired_rag_data(
    db: Session, *, max_rows: int = _DEFAULT_RETENTION_BATCH
) -> dict[str, int]:
    """Boundedly remove expired RAG derivatives, including plaintext evidence.

    Expiry is an authorization check at read time, but it is not a retention
    mechanism by itself.  This intentionally runs even when RAG writes are
    disabled so a paused rollout cannot strand expired evidence indefinitely.
    """
    if not store_ready(db):
        return {"snapshots": 0, "query_cache": 0}
    limit = _bounded_limit(max_rows)
    try:
        result = _prune_expired_rag_data(db, limit)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def _prune_expired_rag_data(db: Session, limit: int) -> dict[str, int]:
    """Execute bounded expiry deletes in the caller's transaction."""
    snapshots = db.execute(text("""
            WITH expired AS (
                SELECT id
                FROM rag_context_snapshots_v2
                WHERE expires_at <= CURRENT_TIMESTAMP
                ORDER BY expires_at, id
                LIMIT :limit
            )
            DELETE FROM rag_context_snapshots_v2 AS snapshot
            USING expired
            WHERE snapshot.id = expired.id
        """), {"limit": limit})
    cache = db.execute(text("""
            WITH expired AS (
                SELECT scope_key, query_hash, embedding_identity, dimensions
                FROM rag_query_embedding_cache_v2
                WHERE expires_at <= CURRENT_TIMESTAMP
                ORDER BY expires_at, scope_key, query_hash, embedding_identity,
                         dimensions
                LIMIT :limit
            )
            DELETE FROM rag_query_embedding_cache_v2 AS cache
            USING expired
            WHERE cache.scope_key = expired.scope_key
              AND cache.query_hash = expired.query_hash
              AND cache.embedding_identity = expired.embedding_identity
              AND cache.dimensions = expired.dimensions
        """), {"limit": limit})
    return {
        "snapshots": int(snapshots.rowcount or 0),
        "query_cache": int(cache.rowcount or 0),
    }


def purge_snapshots_for_sources(
    db: Session,
    sources: Iterable[tuple[str, str]],
    *,
    max_rows: int = _DEFAULT_RETENTION_BATCH,
) -> int:
    """Delete at most ``max_rows`` snapshots referenced by revoked sources.

    Source ownership is a migration-owned, indexed relation rather than a JSON
    scan.  A caller that needs synchronous full removal can use
    ``purge_all_snapshots_for_sources``; each one of its transactions remains
    bounded by this function's explicit limit.
    """
    if not store_ready(db):
        return 0
    wanted = _source_pairs(sources)
    if not wanted:
        return 0
    limit = _bounded_limit(max_rows)
    try:
        rows = db.execute(text("""
            SELECT DISTINCT reference.snapshot_id
            FROM rag_context_snapshot_sources_v2 AS reference
            JOIN unnest(
                CAST(:source_types AS text[]), CAST(:source_ids AS text[])
            ) AS wanted(source_type, source_id)
              ON reference.source_type = wanted.source_type
             AND reference.source_id = wanted.source_id
            ORDER BY reference.snapshot_id
            LIMIT :limit
        """), {
            "source_types": [source_type for source_type, _source_id in wanted],
            "source_ids": [source_id for _source_type, source_id in wanted],
            "limit": limit,
        }).all()
        count = _delete_snapshot_ids(db, (row.snapshot_id for row in rows))
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise


def purge_all_snapshots_for_sources(
    db: Session,
    sources: Iterable[tuple[str, str]],
    *,
    batch_size: int = _DEFAULT_RETENTION_BATCH,
) -> int:
    """Synchronously drain a revoked source's indexed snapshot references.

    Every batch commits independently so a high-fanout source cannot hold one
    long transaction.  The relation is durable, so a process crash leaves the
    remaining references discoverable by the next caller rather than requiring
    a fragile full-table JSON rescan.
    """
    wanted = _source_pairs(sources)
    if not wanted:
        return 0
    total = 0
    limit = _bounded_limit(batch_size)
    while True:
        deleted = purge_snapshots_for_sources(db, wanted, max_rows=limit)
        total += deleted
        if deleted < limit:
            return total


def _pending_source_purge_key(source_type: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{source_type}|{source_id}".encode("utf-8")).hexdigest()
    return f"{_PENDING_SOURCE_PURGE_PREFIX}{digest}"


def queue_source_snapshot_purge(
    db: Session, sources: Iterable[tuple[str, str]]
) -> list[SourceSnapshotPurgeIntent]:
    """Durably queue exact source cleanup in the caller's source transaction."""
    intents: list[SourceSnapshotPurgeIntent] = []
    for source_type, source_id in _source_pairs(sources):
        # A deterministic key coalesces work for one source, but a fresh value
        # is required for compare-and-delete after an independently committed
        # snapshot purge.  Otherwise a slow earlier drainer can erase an
        # intent committed by a later source mutation.
        value = canonical_json({
            "source_type": source_type,
            "source_id": source_id,
            "nonce": str(uuid.uuid4()),
        })
        db.execute(text("""
            INSERT INTO rag_v2_schema_meta (key, value)
            VALUES (:key, :value)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
        """), {
            "key": _pending_source_purge_key(source_type, source_id),
            "value": value,
        })
        intents.append(SourceSnapshotPurgeIntent(source_type, source_id, value))
    return intents


def clear_queued_source_snapshot_purge(
    db: Session,
    source_type: str,
    source_id: str,
    *,
    expected_value: str,
    commit: bool = True,
) -> None:
    """Clear only the durable intent that a completed drain actually saw."""
    db.execute(text("""
        DELETE FROM rag_v2_schema_meta
        WHERE key = :key AND value = :expected_value
    """), {
        "key": _pending_source_purge_key(source_type, source_id),
        "expected_value": expected_value,
    })
    if commit:
        db.commit()


def drain_pending_source_snapshot_purges(
    db: Session, *, max_rows: int = _DEFAULT_RETENTION_BATCH
) -> int:
    """Recover exact source cleanup queued by a process that stopped mid-flow."""
    if not store_ready(db):
        return 0
    limit = _bounded_limit(max_rows)
    rows = db.execute(text("""
        SELECT key, value
        FROM rag_v2_schema_meta
        WHERE key LIKE :prefix
        ORDER BY key
        LIMIT :limit
    """), {"prefix": f"{_PENDING_SOURCE_PURGE_PREFIX}%", "limit": limit}).all()
    completed = 0
    for row in rows:
        try:
            payload = _json_object(row.value, dict)
            source_type = str(payload.get("source_type") or "")
            source_id = str(payload.get("source_id") or "")
            if not source_type or not source_id:
                # The row cannot name a source, so it cannot protect any
                # evidence. Remove it rather than letting one corrupt queue
                # value make every later periodic recovery retry forever.
                # This corrupt value has no valid source identity.  Compare
                # it before removing so a concurrent valid mutation for this
                # deterministic key is never discarded.
                db.execute(text("""
                    DELETE FROM rag_v2_schema_meta
                    WHERE key = :key AND value = :expected_value
                """), {"key": row.key, "expected_value": row.value})
                db.commit()
                completed += 1
                continue
            purge_all_snapshots_for_sources(db, [(source_type, source_id)])
            db.execute(text("""
                DELETE FROM rag_v2_schema_meta
                WHERE key = :key AND value = :expected_value
            """), {"key": row.key, "expected_value": row.value})
            db.commit()
            completed += 1
        except Exception:
            db.rollback()
            raise
    return completed


def purge_ineligible_snapshots(
    db: Session, *, max_rows: int = _DEFAULT_RETENTION_BATCH
) -> int:
    """Boundedly remove snapshots whose indexed source is no longer admissible.

    The normal source mutation paths synchronously drain their references.  A
    process can still die after committing the source/chunk mutation and before
    that follow-up drain, though.  This recovery sweep makes those durable
    references a privacy recovery queue rather than relying on another edit to
    the same source or on TTL expiry.
    """
    if not store_ready(db):
        return 0
    limit = _bounded_limit(max_rows)
    from .store_v2 import _private_comment_indexing_enabled

    try:
        # Create then lock one durable cursor row.  Holding the lock through
        # the scan/delete/cursor update makes two API replicas progress the
        # same page rather than racing the cursor backwards.  If this
        # transaction dies, neither the deletion nor the cursor move commits,
        # so the page is safely retried.
        db.execute(text("""
            INSERT INTO rag_v2_schema_meta (key, value)
            VALUES (:key, '{}')
            ON CONFLICT (key) DO NOTHING
        """), {"key": _INELIGIBLE_SNAPSHOT_CURSOR_KEY})
        cursor_row = db.execute(text("""
            SELECT value
            FROM rag_v2_schema_meta
            WHERE key = :key
            FOR UPDATE
        """), {"key": _INELIGIBLE_SNAPSHOT_CURSOR_KEY}).one()
        cursor_created_at, cursor_id = _ineligible_snapshot_cursor(cursor_row.value)

        # ``LIMIT`` inside a stale predicate alone is not a scan bound: when
        # no rows are stale PostgreSQL can inspect every snapshot first.  Page
        # by monotonic creation order before evaluating authorization, so each
        # interval examines at most ``limit`` snapshot IDs and their indexed
        # ownership references.  UUID primary keys are random: using one as a
        # cursor could defer a newly-created lower UUID for a whole sweep.
        # Keep the first-page and continuation predicates separate.  Folding
        # them into ``cursor IS NULL OR ...`` lets PostgreSQL's generic plan
        # choose a full table scan and sort even after the cursor has moved.
        # These two shapes each map directly onto the (created_at, id) index.
        if cursor_created_at is None:
            candidate_rows = db.execute(text("""
                SELECT id, created_at
                FROM rag_context_snapshots_v2
                ORDER BY created_at, id
                LIMIT :limit
            """), {"limit": limit}).all()
        else:
            candidate_rows = db.execute(text("""
                SELECT id, created_at
                FROM rag_context_snapshots_v2
                WHERE (created_at, id) > (:cursor_created_at, :cursor_id)
                ORDER BY created_at, id
                LIMIT :limit
            """), {
                "cursor_created_at": cursor_created_at,
                "cursor_id": cursor_id,
                "limit": limit,
            }).all()
        if not candidate_rows:
            # Reaching the end starts a fresh, bounded pass next interval.
            db.execute(text("""
                UPDATE rag_v2_schema_meta
                SET value = '{}', updated_at = CURRENT_TIMESTAMP
                WHERE key = :key
            """), {"key": _INELIGIBLE_SNAPSHOT_CURSOR_KEY})
            db.commit()
            return 0

        candidate_ids = [str(row.id) for row in candidate_rows]
        result = db.execute(text("""
            DELETE FROM rag_context_snapshots_v2 AS snapshot
            WHERE snapshot.id = ANY(:candidate_ids)
              AND EXISTS (
                    SELECT 1
                    FROM rag_context_snapshot_sources_v2 AS reference
                    WHERE reference.snapshot_id = snapshot.id
                      AND (
                          reference.source_type NOT IN ('ticket', 'comment', 'kb_article')
                          OR (
                              reference.source_type = 'ticket'
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM tickets AS ticket
                                  WHERE CAST(ticket.id AS text) = reference.source_id
                                    AND LOWER(COALESCE(ticket.external_source, '')) <> 'portal'
                              )
                          )
                          OR (
                              reference.source_type = 'comment'
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM ticket_comments AS comment
                                  JOIN tickets AS ticket ON ticket.id = comment.ticket_id
                                  WHERE comment.id = CASE
                                      -- ``source_id`` is an externally-shaped
                                      -- string.  Guard both numeric casts so a
                                      -- malformed reference still fails closed
                                      -- without disabling the comment PK index.
                                      -- Source IDs are canonical decimal
                                      -- strings.  Reject leading zeros so a
                                      -- malformed reference such as "0001"
                                      -- cannot become an alias for comment 1.
                                      WHEN reference.source_id ~ '^(0|[1-9][0-9]{0,9})$'
                                      THEN CASE
                                          WHEN reference.source_id::numeric <= 2147483647
                                          THEN reference.source_id::integer
                                      END
                                  END
                                    AND LOWER(COALESCE(ticket.external_source, '')) <> 'portal'
                                    AND (
                                        :include_private_comments
                                        OR COALESCE(comment.is_private, false) = false
                                    )
                              )
                          )
                          OR (
                              reference.source_type = 'kb_article'
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM kb_articles AS article
                                  WHERE CAST(article.id AS text) = reference.source_id
                                    AND article.status = 'published'
                                    AND article.reviewer_id IS NOT NULL
                                    AND (
                                        article.author_id IS NULL
                                        OR article.reviewer_id <> article.author_id
                                    )
                              )
                          )
                      )
                )
        """), {
            "include_private_comments": _private_comment_indexing_enabled(),
            "candidate_ids": candidate_ids,
        })
        last_candidate = candidate_rows[-1]
        db.execute(text("""
            UPDATE rag_v2_schema_meta
            SET value = :cursor, updated_at = CURRENT_TIMESTAMP
            WHERE key = :key
        """), {
            "key": _INELIGIBLE_SNAPSHOT_CURSOR_KEY,
            "cursor": canonical_json({
                "created_at": last_candidate.created_at.isoformat(),
                "id": str(last_candidate.id),
            }),
        })
        db.commit()
        return int(result.rowcount or 0)
    except Exception:
        db.rollback()
        raise


def auth_fingerprint(
    *,
    actor_id: str,
    actor_role: str,
    include_private_comments: bool,
    allowed_assignee_id: Optional[str],
    scope: str | None = None,
) -> str:
    payload = canonical_json({
        "actor_id": str(actor_id),
        "actor_role": str(actor_role),
        "allowed_assignee_id": (
            str(allowed_assignee_id) if allowed_assignee_id is not None else None
        ),
        "include_private_comments": bool(include_private_comments),
        "scope_key": scope or scope_key(),
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for item in results:
        required = (
            item.get("chunk_id"),
            item.get("content_hash"),
            item.get("parent_hash"),
            item.get("source_type"),
            item.get("source_id"),
        )
        if not all(required):
            return []
        manifest.append({
            "chunk_id": str(item["chunk_id"]),
            "content_hash": str(item["content_hash"]),
            "parent_hash": str(item["parent_hash"]),
            "source_type": str(item["source_type"]),
            "source_id": str(item["source_id"]),
        })
    return manifest


def _manifest_is_current(
    db: Session,
    manifest: list[dict[str, str]],
    *,
    include_private_comments: bool,
    allowed_assignee_id: Optional[str],
) -> bool:
    for item in manifest:
        source = authoritative_source(
            db, item["source_type"], item["source_id"], for_update=False
        )
        if source is None or source.parent_hash != item["parent_hash"]:
            return False
        if (
            allowed_assignee_id is not None
            and source.source_type != "kb_article"
        ):
            from ..database import TicketRecord

            ticket = db.query(TicketRecord).filter(
                TicketRecord.id == source.ticket_id,
                TicketRecord.assignee_id == allowed_assignee_id,
            ).first()
            if ticket is None:
                return False
        if source.source_type == "comment" and not include_private_comments:
            if bool(source.metadata.get("is_private")):
                return False
        row = db.execute(text("""
            SELECT 1
            FROM ticket_search_chunks_v2
            WHERE chunk_id = :chunk_id
              AND scope_key = :scope_key
              AND content_hash = :content_hash
              AND parent_hash = :parent_hash
              AND source_type = :source_type
              AND source_id = :source_id
            LIMIT 1
        """), {**item, "scope_key": scope_key()}).first()
        if row is None:
            return False
    return True


def create_snapshot(
    db: Session,
    *,
    actor_id: str,
    actor_role: str,
    include_private_comments: bool,
    allowed_assignee_id: Optional[str],
    query: str,
    embedding_identity: str,
    packed_evidence: list[dict[str, Any]],
    citation_allowlist: dict[str, dict[str, Any]],
    retrieval_results: list[dict[str, Any]],
    ai_job_id: Optional[str] = None,
) -> Optional[dict[str, str]]:
    if not store_ready(db):
        return None
    manifest = _manifest(retrieval_results)
    if not manifest or not _manifest_is_current(
        db,
        manifest,
        include_private_comments=include_private_comments,
        allowed_assignee_id=allowed_assignee_id,
    ):
        db.rollback()
        return None
    scope = scope_key()
    generation = corpus_generation(db, scope)
    fingerprint = auth_fingerprint(
        actor_id=actor_id,
        actor_role=actor_role,
        include_private_comments=include_private_comments,
        allowed_assignee_id=allowed_assignee_id,
        scope=scope,
    )
    digest_payload = {
        "scope_key": scope,
        "auth_fingerprint": fingerprint,
        "corpus_generation": generation,
        "embedding_identity": embedding_identity,
        "query_hash": query_hash(query, embedding_identity, scope),
        "evidence": packed_evidence,
        "manifest": manifest,
        "citation_allowlist": citation_allowlist,
    }
    digest = hashlib.sha256(
        canonical_json(digest_payload).encode("utf-8")
    ).hexdigest()
    snapshot_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(
        seconds=min(snapshot_ttl_seconds(), 86400)
    )
    # Keep opportunistic cleanup bounded as well; startup performs the same
    # unified maintenance even when no later analysis request arrives.
    try:
        _prune_expired_rag_data(db, _DEFAULT_RETENTION_BATCH)
        db.execute(text("""
            INSERT INTO rag_context_snapshots_v2 (
            id, ai_job_id, scope_key, actor_id, auth_fingerprint,
            corpus_generation, embedding_identity, query_hash,
            evidence_json, chunk_manifest_json, citation_allowlist_json,
            digest, expires_at
        ) VALUES (
            :id, :ai_job_id, :scope_key, :actor_id, :auth_fingerprint,
            :corpus_generation, :embedding_identity, :query_hash,
            CAST(:evidence_json AS jsonb), CAST(:manifest_json AS jsonb),
            CAST(:citation_json AS jsonb), :digest, :expires_at
        )
        """), {
            "id": snapshot_id,
            "ai_job_id": ai_job_id,
            "scope_key": scope,
            "actor_id": str(actor_id),
            "auth_fingerprint": fingerprint,
            "corpus_generation": generation,
            "embedding_identity": embedding_identity,
            "query_hash": digest_payload["query_hash"],
            "evidence_json": canonical_json(packed_evidence),
            "manifest_json": canonical_json(manifest),
            "citation_json": canonical_json(citation_allowlist),
            "digest": digest,
            "expires_at": expires_at,
        })
        db.execute(text("""
            INSERT INTO rag_context_snapshot_sources_v2 (
            snapshot_id, source_type, source_id
        ) VALUES (
            :snapshot_id, :source_type, :source_id
        )
        """), [
            {
                "snapshot_id": snapshot_id,
                "source_type": source_type,
                "source_id": source_id,
            }
            for source_type, source_id in sorted({(
                entry["source_type"], entry["source_id"]
            ) for entry in manifest})
        ])
        db.commit()
    except Exception:
        # Evidence and its ownership references are one unit: an insertion
        # failure must never leave plaintext evidence without a purge handle.
        db.rollback()
        raise
    return {"snapshot_id": snapshot_id, "snapshot_digest": digest}


def _json_object(value: Any, expected: type) -> Any:
    if isinstance(value, expected):
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return expected()
    return decoded if isinstance(decoded, expected) else expected()


def load_snapshot(
    db: Session,
    snapshot_id: str,
    *,
    actor_id: str,
    actor_role: str,
    include_private_comments: bool,
    allowed_assignee_id: Optional[str],
    embedding_identity: str,
) -> Optional[dict[str, Any]]:
    """Load only a still-current, still-authorized immutable snapshot."""
    if not store_ready(db):
        return None
    scope = scope_key()
    expected_fingerprint = auth_fingerprint(
        actor_id=actor_id,
        actor_role=actor_role,
        include_private_comments=include_private_comments,
        allowed_assignee_id=allowed_assignee_id,
        scope=scope,
    )
    row = db.execute(text("""
        SELECT *
        FROM rag_context_snapshots_v2
        WHERE id = :id
          AND scope_key = :scope_key
          AND actor_id = :actor_id
          AND auth_fingerprint = :auth_fingerprint
          AND embedding_identity = :embedding_identity
          AND expires_at > CURRENT_TIMESTAMP
        LIMIT 1
    """), {
        "id": snapshot_id,
        "scope_key": scope,
        "actor_id": str(actor_id),
        "auth_fingerprint": expected_fingerprint,
        "embedding_identity": embedding_identity,
    }).first()
    if row is None or int(row.corpus_generation) != corpus_generation(db, scope):
        db.rollback()
        return None
    manifest = _json_object(row.chunk_manifest_json, list)
    if not manifest or not _manifest_is_current(
        db,
        manifest,
        include_private_comments=include_private_comments,
        allowed_assignee_id=allowed_assignee_id,
    ):
        db.rollback()
        return None
    evidence = _json_object(row.evidence_json, list)
    citations = _json_object(row.citation_allowlist_json, dict)
    digest_payload = {
        "scope_key": scope,
        "auth_fingerprint": expected_fingerprint,
        "corpus_generation": int(row.corpus_generation),
        "embedding_identity": embedding_identity,
        "query_hash": str(row.query_hash),
        "evidence": evidence,
        "manifest": manifest,
        "citation_allowlist": citations,
    }
    digest = hashlib.sha256(
        canonical_json(digest_payload).encode("utf-8")
    ).hexdigest()
    if digest != row.digest:
        db.rollback()
        return None
    db.rollback()
    return {
        "snapshot_id": str(row.id),
        "snapshot_digest": digest,
        "evidence": evidence,
        "citation_allowlist": citations,
    }
