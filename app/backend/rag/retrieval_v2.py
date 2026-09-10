from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import text

from ..database import SessionLocal
from .chunking import canonical_query
from .config import (
    dimensions,
    query_cache_max_rows,
    query_cache_ttl_seconds,
    scope_key,
)
from .store_v2 import store_ready


_ALLOWED_SOURCE_TYPES = {"ticket", "comment", "kb_article"}
_AUTHORITY_PRIORITY = {
    "external_report": 1,
    "authenticated_report": 2,
    "internal_comment": 3,
    "published_kb": 4,
}
_RRF_K = 60
_NON_KB_POOL = 40
_KB_POOL = 16

_AUTH_PREDICATE = """
AND (
    (
        chunk.source_type = 'ticket'
        AND EXISTS (
            SELECT 1
            FROM tickets AS source_ticket
            WHERE source_ticket.id = chunk.source_id
              AND chunk.ticket_id = source_ticket.id
              AND LOWER(COALESCE(source_ticket.external_source, '')) <> 'portal'
              AND (
                    :allowed_assignee_id IS NULL
                    OR source_ticket.assignee_id = :allowed_assignee_id
              )
        )
    )
    OR (
        chunk.source_type = 'comment'
        AND EXISTS (
            SELECT 1
            FROM ticket_comments AS source_comment
            JOIN tickets AS source_ticket
              ON source_ticket.id = source_comment.ticket_id
            WHERE CAST(source_comment.id AS text) = chunk.source_id
              AND chunk.ticket_id = source_ticket.id
              AND LOWER(COALESCE(source_ticket.external_source, '')) <> 'portal'
              AND (
                    :allowed_assignee_id IS NULL
                    OR source_ticket.assignee_id = :allowed_assignee_id
              )
              AND (
                    :include_private_comments
                    OR COALESCE(source_comment.is_private, false) = false
              )
        )
    )
    OR (
        chunk.source_type = 'kb_article'
        AND EXISTS (
            SELECT 1
            FROM kb_articles AS source_article
            WHERE source_article.id = chunk.source_id
              AND source_article.status = 'published'
              AND source_article.reviewer_id IS NOT NULL
              AND (
                    source_article.author_id IS NULL
                    OR source_article.reviewer_id <> source_article.author_id
              )
        )
    )
)
"""


def _vector_literal(values: Iterable[float]) -> str:
    checked = [float(value) for value in values]
    if len(checked) != dimensions() or any(not math.isfinite(value) for value in checked):
        raise ValueError("invalid query embedding")
    return "[" + ",".join(f"{value:.8f}" for value in checked) + "]"


def query_hash(query: str, embedding_identity: str, scope: str | None = None) -> str:
    canonical = canonical_query(query)
    payload = "|".join((scope or scope_key(), canonical, embedding_identity, str(dimensions())))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_vector(raw: Any) -> Optional[list[float]]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value.startswith("[") or not value.endswith("]"):
        return None
    try:
        parsed = [float(item) for item in value[1:-1].split(",") if item]
    except ValueError:
        return None
    if len(parsed) != dimensions() or any(not math.isfinite(item) for item in parsed):
        return None
    return parsed


def _cache_get(scope: str, digest: str, identity: str) -> Optional[list[float]]:
    db = SessionLocal()
    try:
        if not store_ready(db):
            return None
        row = db.execute(text("""
            UPDATE rag_query_embedding_cache_v2
            SET last_accessed_at = CURRENT_TIMESTAMP,
                hit_count = hit_count + 1
            WHERE scope_key = :scope_key
              AND query_hash = :query_hash
              AND embedding_identity = :embedding_identity
              AND dimensions = :dimensions
              AND expires_at > CURRENT_TIMESTAMP
            RETURNING embedding::text AS embedding
        """), {
            "scope_key": scope,
            "query_hash": digest,
            "embedding_identity": identity,
            "dimensions": dimensions(),
        }).first()
        db.commit()
        return _parse_vector(row.embedding) if row else None
    except Exception:
        db.rollback()
        return None
    finally:
        db.close()


def _cache_put(scope: str, digest: str, identity: str, embedding: list[float]) -> None:
    db = SessionLocal()
    try:
        if not store_ready(db):
            return
        expires_at = datetime.utcnow() + timedelta(seconds=query_cache_ttl_seconds())
        db.execute(text("""
            INSERT INTO rag_query_embedding_cache_v2 (
                scope_key, query_hash, embedding_identity, dimensions,
                embedding, expires_at
            ) VALUES (
                :scope_key, :query_hash, :embedding_identity, :dimensions,
                CAST(:embedding AS vector), :expires_at
            )
            ON CONFLICT (scope_key, query_hash, embedding_identity, dimensions)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                created_at = CURRENT_TIMESTAMP,
                last_accessed_at = CURRENT_TIMESTAMP,
                expires_at = EXCLUDED.expires_at,
                hit_count = 0
        """), {
            "scope_key": scope,
            "query_hash": digest,
            "embedding_identity": identity,
            "dimensions": dimensions(),
            "embedding": _vector_literal(embedding),
            "expires_at": expires_at,
        })
        db.execute(text(
            "DELETE FROM rag_query_embedding_cache_v2 "
            "WHERE expires_at <= CURRENT_TIMESTAMP"
        ))
        db.execute(text("""
            DELETE FROM rag_query_embedding_cache_v2 AS cache
            WHERE (cache.scope_key, cache.query_hash, cache.embedding_identity, cache.dimensions)
                  IN (
                      SELECT scope_key, query_hash, embedding_identity, dimensions
                      FROM rag_query_embedding_cache_v2
                      ORDER BY last_accessed_at DESC
                      OFFSET :max_rows
                  )
        """), {"max_rows": query_cache_max_rows()})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


async def _query_embedding(query: str, identity: str, scope: str) -> Optional[list[float]]:
    digest = query_hash(query, identity, scope)
    cached = await asyncio.to_thread(_cache_get, scope, digest, identity)
    if cached is not None:
        return cached
    from .. import ticket_vectors

    embedded = await ticket_vectors._embed_text(canonical_query(query))
    if embedded is not None:
        await asyncio.to_thread(_cache_put, scope, digest, identity, embedded)
    return embedded


def _base_params(
    scope: str,
    source_types: list[str],
    include_private_comments: bool,
    allowed_assignee_id: Optional[str],
) -> dict[str, Any]:
    return {
        "scope_key": scope,
        "source_types": source_types,
        "include_private_comments": include_private_comments,
        "allowed_assignee_id": allowed_assignee_id,
        "non_kb_limit": _NON_KB_POOL,
        "non_kb_scan_limit": _NON_KB_POOL * 4,
        "kb_limit": _KB_POOL,
    }


def _rows(db, statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in db.execute(text(statement), params).all()]


def _fetch_lexical(
    query: str,
    scope: str,
    source_types: list[str],
    include_private_comments: bool,
    allowed_assignee_id: Optional[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    db = SessionLocal()
    try:
        if not store_ready(db):
            raise RuntimeError("RAG v2 store is unavailable")
        params = _base_params(
            scope, source_types, include_private_comments, allowed_assignee_id
        )
        params["keyword_query"] = query
        non_kb = _rows(db, f"""
            WITH candidates AS MATERIALIZED (
                SELECT chunk.*,
                       CASE WHEN chunk.source_type = 'ticket' THEN (
                           SELECT source_ticket.external_source
                           FROM tickets AS source_ticket
                           WHERE source_ticket.id = chunk.source_id
                           LIMIT 1
                       ) END AS authoritative_external_source,
                       ts_rank_cd(
                           to_tsvector(
                               'simple'::regconfig,
                               COALESCE(chunk.section_path, '') || ' ' || chunk.content
                           ),
                           plainto_tsquery('simple'::regconfig, :keyword_query)
                       ) AS signal_score
                FROM ticket_search_chunks_v2 AS chunk
                WHERE chunk.scope_key = :scope_key
                  AND chunk.source_type = ANY(:source_types)
                  AND chunk.source_type IN ('ticket', 'comment')
                  AND to_tsvector(
                      'simple'::regconfig,
                      COALESCE(chunk.section_path, '') || ' ' || chunk.content
                  ) @@ plainto_tsquery('simple'::regconfig, :keyword_query)
                  {_AUTH_PREDICATE}
                ORDER BY signal_score DESC, chunk.updated_at DESC,
                         chunk.source_type, chunk.source_id,
                         chunk.chunk_index, chunk.chunk_id
                LIMIT :non_kb_scan_limit
            ), ranked AS (
                SELECT candidates.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticket_id
                           ORDER BY signal_score DESC, updated_at DESC,
                                    source_type, source_id, chunk_index, chunk_id
                       ) AS parent_rank
                FROM candidates
            )
            SELECT * FROM ranked
            WHERE parent_rank <= 2
            ORDER BY signal_score DESC, updated_at DESC,
                     source_type, source_id, chunk_index, chunk_id
            LIMIT :non_kb_limit
        """, params)
        kb = _rows(db, f"""
            SELECT chunk.*, NULL AS authoritative_external_source,
                   ts_rank_cd(
                       to_tsvector(
                           'simple'::regconfig,
                           COALESCE(chunk.section_path, '') || ' ' || chunk.content
                       ),
                       plainto_tsquery('simple'::regconfig, :keyword_query)
                   ) AS signal_score
            FROM ticket_search_chunks_v2 AS chunk
            WHERE chunk.scope_key = :scope_key
              AND chunk.source_type = 'kb_article'
              AND chunk.source_type = ANY(:source_types)
              AND to_tsvector(
                  'simple'::regconfig,
                  COALESCE(chunk.section_path, '') || ' ' || chunk.content
              ) @@ plainto_tsquery('simple'::regconfig, :keyword_query)
              {_AUTH_PREDICATE}
            ORDER BY signal_score DESC, chunk.updated_at DESC,
                     chunk.source_id, chunk.chunk_index, chunk.chunk_id
            LIMIT :kb_limit
        """, params)
        db.rollback()
        return non_kb, kb
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _fetch_vector(
    embedding: list[float],
    identity: str,
    minimum_score: float,
    scope: str,
    source_types: list[str],
    include_private_comments: bool,
    allowed_assignee_id: Optional[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    db = SessionLocal()
    try:
        if not store_ready(db):
            raise RuntimeError("RAG v2 store is unavailable")
        params = _base_params(
            scope, source_types, include_private_comments, allowed_assignee_id
        )
        params.update({
            "embedding": _vector_literal(embedding),
            "embedding_identity": identity,
            "minimum_score": minimum_score,
        })
        non_kb = _rows(db, f"""
            WITH candidates AS MATERIALIZED (
                SELECT chunk.*,
                       CASE WHEN chunk.source_type = 'ticket' THEN (
                           SELECT source_ticket.external_source
                           FROM tickets AS source_ticket
                           WHERE source_ticket.id = chunk.source_id
                           LIMIT 1
                       ) END AS authoritative_external_source,
                       1 - (chunk.embedding <=> CAST(:embedding AS vector)) AS signal_score
                FROM ticket_search_chunks_v2 AS chunk
                WHERE chunk.scope_key = :scope_key
                  AND chunk.embedding_state = 'ready'
                  AND chunk.embedding IS NOT NULL
                  AND chunk.embedding_identity = :embedding_identity
                  AND 1 - (chunk.embedding <=> CAST(:embedding AS vector))
                      >= :minimum_score
                  AND chunk.source_type = ANY(:source_types)
                  AND chunk.source_type IN ('ticket', 'comment')
                  {_AUTH_PREDICATE}
                ORDER BY chunk.embedding <=> CAST(:embedding AS vector),
                         chunk.updated_at DESC, chunk.source_type,
                         chunk.source_id, chunk.chunk_index, chunk.chunk_id
                LIMIT :non_kb_scan_limit
            ), ranked AS (
                SELECT candidates.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticket_id
                           ORDER BY embedding <=> CAST(:embedding AS vector),
                                    updated_at DESC, source_type, source_id,
                                    chunk_index, chunk_id
                       ) AS parent_rank
                FROM candidates
            )
            SELECT * FROM ranked
            WHERE parent_rank <= 2
            ORDER BY embedding <=> CAST(:embedding AS vector),
                     updated_at DESC, source_type, source_id, chunk_index, chunk_id
            LIMIT :non_kb_limit
        """, params)
        kb = _rows(db, f"""
            SELECT chunk.*, NULL AS authoritative_external_source,
                   1 - (chunk.embedding <=> CAST(:embedding AS vector)) AS signal_score
            FROM ticket_search_chunks_v2 AS chunk
            WHERE chunk.scope_key = :scope_key
              AND chunk.embedding_state = 'ready'
              AND chunk.embedding IS NOT NULL
              AND chunk.embedding_identity = :embedding_identity
              AND 1 - (chunk.embedding <=> CAST(:embedding AS vector))
                  >= :minimum_score
              AND chunk.source_type = 'kb_article'
              AND chunk.source_type = ANY(:source_types)
              {_AUTH_PREDICATE}
            ORDER BY chunk.embedding <=> CAST(:embedding AS vector),
                     chunk.updated_at DESC, chunk.source_id,
                     chunk.chunk_index, chunk.chunk_id
            LIMIT :kb_limit
        """, params)
        db.rollback()
        return non_kb, kb
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _authority(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    if row["source_type"] == "kb_article":
        return "published_kb"
    if row["source_type"] == "comment":
        return "internal_comment"
    external = str(row.get("authoritative_external_source") or "").strip().lower()
    metadata["external_source"] = external
    return "external_report" if external and external != "manual" else "authenticated_report"


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(row.get("metadata_json"))
    authority = _authority(row, metadata)
    source_type = str(row["source_type"])
    source_id = str(row["source_id"])
    ticket_id = str(row["ticket_id"]) if row.get("ticket_id") is not None else None
    provenance = {
        "authority": authority,
        "source_type": source_type,
        "source_id": source_id,
        "ticket_id": ticket_id,
    }
    if authority == "external_report":
        provenance["external_source"] = metadata.get("external_source") or ""
    metadata["authority"] = authority
    metadata["provenance"] = provenance
    return {
        "chunk_id": str(row["chunk_id"]),
        "content_hash": str(row["content_hash"]),
        "parent_hash": str(row["parent_hash"]),
        "source_revision": str(row["source_revision"]),
        "source_type": source_type,
        "source_id": source_id,
        "ticket_id": ticket_id,
        "title": str(metadata.get("display_title") or row.get("section_path") or "")[:300],
        "snippet": str(row.get("content") or "")[:700].strip(),
        "metadata": metadata,
        "authority": authority,
        "provenance": provenance,
    }


def reciprocal_rank_fusion(
    signals: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Fuse only ordinal ranks so incomparable raw scores never mix."""
    aggregated: dict[str, dict[str, Any]] = {}
    signal_kinds: dict[str, set[str]] = {}
    best_rank: dict[str, int] = {}
    for signal_name, rows in signals.items():
        kind = signal_name.split("_", 1)[0]
        seen: set[str] = set()
        for rank, row in enumerate(rows, start=1):
            item = _shape(row)
            identity = item["chunk_id"]
            if identity in seen:
                continue
            seen.add(identity)
            if identity not in aggregated:
                aggregated[identity] = {**item, "score": 0.0}
            aggregated[identity]["score"] += 1.0 / (_RRF_K + rank)
            signal_kinds.setdefault(identity, set()).add(kind)
            best_rank[identity] = min(rank, best_rank.get(identity, rank))

    result = list(aggregated.values())
    for item in result:
        identity = item["chunk_id"]
        kinds = signal_kinds[identity]
        item["match_method"] = "hybrid" if {"lexical", "vector"} <= kinds else next(iter(kinds))
        item["score"] = round(float(item["score"]), 8)
        item["_both"] = int({"lexical", "vector"} <= kinds)
        item["_best_rank"] = best_rank[identity]
    result.sort(key=lambda item: (
        -float(item["score"]),
        -int(item["_both"]),
        -_AUTHORITY_PRIORITY.get(str(item["authority"]), 0),
        int(item["_best_rank"]),
        str(item["source_type"]),
        str(item["source_id"]),
        int(next(
            (row.get("chunk_index", 0) for rows in signals.values() for row in rows
             if str(row.get("chunk_id")) == item["chunk_id"]),
            0,
        )),
        str(item["chunk_id"]),
    ))
    for item in result:
        item.pop("_both", None)
        item.pop("_best_rank", None)
    return result


def _evidence_fingerprint(item: dict[str, Any]) -> str:
    normalized = unicodedata.normalize("NFKC", str(item.get("snippet") or "")).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def diversify(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    fingerprints: dict[str, int] = {}
    for item in results:
        fingerprint = _evidence_fingerprint(item)
        existing_index = fingerprints.get(fingerprint)
        if existing_index is None:
            fingerprints[fingerprint] = len(unique)
            unique.append(item)
            continue
        existing = unique[existing_index]
        if _AUTHORITY_PRIORITY.get(str(item.get("authority")), 0) > _AUTHORITY_PRIORITY.get(
            str(existing.get("authority")), 0
        ):
            unique[existing_index] = item

    deduplicated: list[dict[str, Any]] = []
    parent_counts: dict[tuple[str, str], int] = {}
    ticket_counts: dict[str, int] = {}
    for item in unique:
        parent = (str(item["source_type"]), str(item["source_id"]))
        ticket_id = item.get("ticket_id")
        if parent_counts.get(parent, 0) >= 2:
            continue
        if item["source_type"] != "kb_article" and ticket_id is not None:
            if ticket_counts.get(str(ticket_id), 0) >= 2:
                continue
            ticket_counts[str(ticket_id)] = ticket_counts.get(str(ticket_id), 0) + 1
        parent_counts[parent] = parent_counts.get(parent, 0) + 1
        deduplicated.append(item)

    selected = deduplicated[:limit]
    selected_ids = {item["chunk_id"] for item in selected}
    available_kb = [
        item for item in deduplicated
        if item["authority"] == "published_kb" and item["chunk_id"] not in selected_ids
    ]
    kb_count = sum(item["authority"] == "published_kb" for item in selected)
    while selected and available_kb and kb_count < min(2, limit):
        replacement = next(
            (
                index for index in range(len(selected) - 1, -1, -1)
                if selected[index]["authority"] != "published_kb"
            ),
            None,
        )
        if replacement is None:
            break
        selected[replacement] = available_kb.pop(0)
        kb_count += 1
    return selected


async def retrieve_ticket_context_v2(
    query: str,
    *,
    limit: int = 8,
    source_types: Optional[list[str]] = None,
    include_private_comments: bool = False,
    allowed_assignee_id: Optional[str] = None,
) -> dict[str, Any]:
    canonical = canonical_query(query)
    if not canonical:
        return {"query": query, "match_method": "hybrid", "results": []}
    requested = source_types or ["ticket", "comment", "kb_article"]
    source_types = [item for item in requested if item in _ALLOWED_SOURCE_TYPES]
    if not source_types:
        return {"query": query, "match_method": "hybrid", "results": []}
    limit = max(1, min(int(limit or 8), 10))
    scope = scope_key()
    from ..ticket_vectors import (
        _embedding_identity,
        _minimum_vector_score,
        embedding_enabled,
    )

    identity = _embedding_identity()
    lexical_task = asyncio.create_task(asyncio.to_thread(
        _fetch_lexical,
        canonical,
        scope,
        source_types,
        include_private_comments,
        allowed_assignee_id,
    ))
    embedding_task = (
        asyncio.create_task(_query_embedding(canonical, identity, scope))
        if embedding_enabled()
        else None
    )
    try:
        lexical_non_kb, lexical_kb = await lexical_task
    except Exception:
        if embedding_task is not None:
            embedding_task.cancel()
            await asyncio.gather(embedding_task, return_exceptions=True)
        # Lexical retrieval includes the authoritative predicates. A database
        # failure here must fail closed rather than returning unchecked data.
        raise
    vector_non_kb: list[dict[str, Any]] = []
    vector_kb: list[dict[str, Any]] = []
    if embedding_task is not None:
        try:
            embedding = await embedding_task
            if embedding is not None:
                vector_non_kb, vector_kb = await asyncio.to_thread(
                    _fetch_vector,
                    embedding,
                    identity,
                    _minimum_vector_score(),
                    scope,
                    source_types,
                    include_private_comments,
                    allowed_assignee_id,
                )
        except Exception as exc:
            print(
                "[rag-v2] vector retrieval unavailable; using authorized lexical "
                f"results kind={type(exc).__name__}"
            )
    fused = reciprocal_rank_fusion({
        "lexical_non_kb": lexical_non_kb,
        "lexical_kb": lexical_kb,
        "vector_non_kb": vector_non_kb,
        "vector_kb": vector_kb,
    })
    selected = diversify(fused, limit)
    method = "hybrid" if vector_non_kb or vector_kb else "lexical"
    return {"query": query, "match_method": method, "results": selected}
