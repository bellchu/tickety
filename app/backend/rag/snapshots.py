from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .chunking import canonical_json
from .config import scope_key, snapshot_ttl_seconds
from .retrieval_v2 import query_hash
from .store_v2 import authoritative_source, corpus_generation, store_ready


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
    db.execute(text("DELETE FROM rag_context_snapshots_v2 WHERE expires_at <= CURRENT_TIMESTAMP"))
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
    db.commit()
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
