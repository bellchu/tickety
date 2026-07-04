import asyncio
import hashlib
import json
import os
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import KbArticleRecord, SessionLocal, TicketCommentRecord, TicketRecord
from .privacy import redact_text


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9._-]{1,}", re.IGNORECASE)


def embedding_enabled() -> bool:
    return (os.getenv("TICKET_EMBEDDING_ENABLED", "") or "").strip().lower() in _TRUE_VALUES


def embedding_model() -> str:
    return (os.getenv("TICKET_EMBEDDING_MODEL") or _DEFAULT_EMBEDDING_MODEL).strip()


def _dimensions() -> int:
    try:
        return int(os.getenv("TICKET_EMBEDDING_DIMENSIONS", "1536") or "1536")
    except ValueError:
        return 1536


def _embedding_kwargs() -> dict[str, Any]:
    model = embedding_model()
    kwargs: dict[str, Any] = {"model": model}
    if model.startswith("openai/"):
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("TICKET_EMBEDDING_API_BASE") or os.getenv("OPENAI_API_BASE")
        if api_base:
            kwargs["api_base"] = api_base
    elif model.startswith("custom/"):
        kwargs["model"] = model[7:]
        kwargs["api_key"] = os.getenv("CUSTOM_API_KEY")
        kwargs["custom_llm_provider"] = os.getenv("CUSTOM_PROVIDER_TYPE") or "openai"
        api_base = os.getenv("TICKET_EMBEDDING_API_BASE") or os.getenv("CUSTOM_API_BASE")
        if api_base:
            kwargs["api_base"] = api_base
    return {k: v for k, v in kwargs.items() if v}


def _document_hash(title: str, body: str, metadata: dict[str, Any]) -> str:
    payload = json.dumps(
        {"title": title, "body": body, "metadata": metadata},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


async def _embed_text(text_value: str) -> Optional[list[float]]:
    if not embedding_enabled():
        return None
    kwargs = _embedding_kwargs()
    if not kwargs.get("api_key") and not kwargs.get("custom_llm_provider"):
        return None
    try:
        from litellm import aembedding

        response = await aembedding(input=[redact_text(text_value)], **kwargs)
        data = response.get("data") if isinstance(response, dict) else getattr(response, "data", None)
        first = data[0] if data else None
        embedding = first.get("embedding") if isinstance(first, dict) else getattr(first, "embedding", None)
        if not embedding:
            return None
        return [float(v) for v in embedding]
    except Exception as e:
        print(f"[vectors] embedding failed: {e}")
        return None


def ticket_vector_store_ready(db: Session) -> bool:
    if db.bind.dialect.name != "postgresql":
        return False
    try:
        row = db.execute(text("SELECT to_regclass('ticket_search_documents')")).first()
        return bool(row and row[0])
    except Exception:
        return False


def _row_current(db: Session, source_type: str, source_id: str, content_hash: str) -> bool:
    if not ticket_vector_store_ready(db):
        return False
    row = db.execute(
        text(
            """
            SELECT embedding IS NOT NULL AS has_embedding
            FROM ticket_search_documents
            WHERE source_type = :source_type
              AND source_id = :source_id
              AND content_hash = :content_hash
            LIMIT 1
            """
        ),
        {"source_type": source_type, "source_id": source_id, "content_hash": content_hash},
    ).first()
    if not row:
        return False
    return bool(row.has_embedding) or not embedding_enabled()


async def _upsert_document(
    db: Session,
    *,
    source_type: str,
    source_id: str,
    ticket_id: Optional[str],
    title: str,
    body: str,
    metadata: dict[str, Any],
    force: bool = False,
) -> bool:
    if not ticket_vector_store_ready(db):
        return False

    title = (title or "").strip()
    body = (body or "").strip()
    content_hash = _document_hash(title, body, metadata)
    if not force and _row_current(db, source_type, source_id, content_hash):
        return False

    text_for_embedding = "\n".join([title, body]).strip()
    vector = await _embed_text(text_for_embedding)
    params = {
        "source_type": source_type,
        "source_id": source_id,
        "ticket_id": ticket_id,
        "title": title,
        "body": body,
        "metadata_json": json.dumps(metadata, default=str),
        "content_hash": content_hash,
        "embedding": _vector_literal(vector) if vector else None,
        "embedding_model": embedding_model() if vector else None,
        "embedded_at": datetime.utcnow() if vector else None,
    }
    try:
        db.execute(
            text(
                """
                INSERT INTO ticket_search_documents (
                    source_type, source_id, ticket_id, title, body, metadata_json,
                    content_hash, embedding, embedding_model, embedded_at, updated_at
                )
                VALUES (
                    :source_type, :source_id, :ticket_id, :title, :body, :metadata_json,
                    :content_hash, CAST(:embedding AS vector), :embedding_model,
                    :embedded_at, CURRENT_TIMESTAMP
                )
                ON CONFLICT (source_type, source_id) DO UPDATE SET
                    ticket_id = EXCLUDED.ticket_id,
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    metadata_json = EXCLUDED.metadata_json,
                    content_hash = EXCLUDED.content_hash,
                    embedding = COALESCE(EXCLUDED.embedding, ticket_search_documents.embedding),
                    embedding_model = COALESCE(EXCLUDED.embedding_model, ticket_search_documents.embedding_model),
                    embedded_at = COALESCE(EXCLUDED.embedded_at, ticket_search_documents.embedded_at),
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            params,
        )
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"[vectors] document upsert failed for {source_type}:{source_id}: {e}")
        return False


def _ticket_metadata(ticket: TicketRecord) -> dict[str, Any]:
    return {
        "status": ticket.status,
        "workflow_status": ticket.workflow_status,
        "priority": ticket.priority,
        "category": ticket.category,
        "reporter": ticket.reporter,
        "assignee_id": ticket.assignee_id,
        "ticket_type": ticket.ticket_type,
        "external_source": ticket.external_source,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "resolved_at": ticket.resolved_at,
        "tags": ticket.tags,
    }


async def upsert_ticket_document(db: Session, ticket: TicketRecord, force: bool = False) -> bool:
    body_parts = [
        ticket.description or "",
        f"AI summary: {ticket.summary}" if ticket.summary else "",
        f"AI reasoning: {ticket.ai_reasoning}" if ticket.ai_reasoning else "",
        f"Recommended solution: {ticket.recommended_solution}" if ticket.recommended_solution else "",
    ]
    return await _upsert_document(
        db,
        source_type="ticket",
        source_id=ticket.id,
        ticket_id=ticket.id,
        title=ticket.subject,
        body="\n".join(part for part in body_parts if part),
        metadata=_ticket_metadata(ticket),
        force=force,
    )


async def upsert_comment_document(db: Session, comment: TicketCommentRecord, force: bool = False) -> bool:
    return await _upsert_document(
        db,
        source_type="comment",
        source_id=str(comment.id),
        ticket_id=comment.ticket_id,
        title=f"Ticket comment on {comment.ticket_id}",
        body=comment.body,
        metadata={
            "is_private": comment.is_private,
            "author_id": comment.author_id,
            "author_name": comment.author_name,
            "created_at": comment.created_at,
        },
        force=force,
    )


async def upsert_kb_document(db: Session, article: KbArticleRecord, force: bool = False) -> bool:
    return await _upsert_document(
        db,
        source_type="kb_article",
        source_id=article.id,
        ticket_id=None,
        title=article.title,
        body=article.content or "",
        metadata={
            "slug": article.slug,
            "category": article.category,
            "tags": article.tags,
            "status": article.status,
            "updated_at": article.updated_at,
        },
        force=force,
    )


async def refresh_ticket_documents(db: Session, ticket: TicketRecord, force: bool = False) -> int:
    changed = 0
    if await upsert_ticket_document(db, ticket, force=force):
        changed += 1
    comments = db.query(TicketCommentRecord).filter(
        TicketCommentRecord.ticket_id == ticket.id
    ).all()
    for comment in comments:
        if await upsert_comment_document(db, comment, force=force):
            changed += 1
    return changed


async def _refresh_ticket_by_id(ticket_id: str, force: bool = False) -> int:
    db = SessionLocal()
    try:
        ticket = db.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
        if not ticket:
            return 0
        return await refresh_ticket_documents(db, ticket, force=force)
    finally:
        db.close()


def refresh_ticket_documents_background(db: Session, ticket: TicketRecord, force: bool = False) -> int:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(refresh_ticket_documents(db, ticket, force=force))
    loop.create_task(_refresh_ticket_by_id(ticket.id, force=force))
    return 0


def delete_ticket_documents(db: Session, ticket_id: str) -> None:
    if not ticket_vector_store_ready(db):
        return
    db.execute(
        text("DELETE FROM ticket_search_documents WHERE ticket_id = :ticket_id"),
        {"ticket_id": ticket_id},
    )
    db.commit()


async def backfill_ticket_documents(
    db: Session,
    *,
    limit: int = 200,
    include_comments: bool = True,
    include_kb: bool = True,
    force: bool = False,
) -> dict[str, int | bool]:
    limit = max(1, min(int(limit or 200), 5000))
    result: dict[str, int | bool] = {
        "vector_store_ready": ticket_vector_store_ready(db),
        "tickets_seen": 0,
        "comments_seen": 0,
        "kb_seen": 0,
        "documents_changed": 0,
    }
    if not result["vector_store_ready"]:
        return result

    tickets = db.query(TicketRecord).order_by(TicketRecord.updated_at.desc()).limit(limit).all()
    for ticket in tickets:
        result["tickets_seen"] += 1
        if await upsert_ticket_document(db, ticket, force=force):
            result["documents_changed"] += 1

    if include_comments:
        comments = db.query(TicketCommentRecord).order_by(TicketCommentRecord.created_at.desc()).limit(limit).all()
        for comment in comments:
            result["comments_seen"] += 1
            if await upsert_comment_document(db, comment, force=force):
                result["documents_changed"] += 1

    if include_kb:
        articles = db.query(KbArticleRecord).order_by(KbArticleRecord.updated_at.desc()).limit(limit).all()
        for article in articles:
            result["kb_seen"] += 1
            if await upsert_kb_document(db, article, force=force):
                result["documents_changed"] += 1

    return result


def ticket_vector_status(db: Session) -> dict[str, Any]:
    ready = ticket_vector_store_ready(db)
    result = {
        "vector_store_ready": ready,
        "embedding_enabled": embedding_enabled(),
        "embedding_model": embedding_model(),
        "embedding_dimensions": _dimensions(),
        "documents": 0,
        "embedded_documents": 0,
        "stale_documents": 0,
    }
    if not ready:
        return result
    row = db.execute(
        text(
            """
            SELECT
                COUNT(*) AS documents,
                COUNT(embedding) AS embedded_documents,
                COUNT(*) FILTER (WHERE embedding IS NULL) AS stale_documents
            FROM ticket_search_documents
            """
        )
    ).first()
    if row:
        result.update(
            {
                "documents": int(row.documents or 0),
                "embedded_documents": int(row.embedded_documents or 0),
                "stale_documents": int(row.stale_documents or 0),
            }
        )
    return result


def _terms(query: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "this", "that", "ticket", "issue", "what"}
    return {w.lower() for w in _WORD_RE.findall(query or "") if w.lower() not in stop}


def _keyword_score(query_terms: set[str], title: str, body: str, metadata: dict[str, Any]) -> float:
    haystack = " ".join([title or "", body or "", json.dumps(metadata, default=str)]).lower()
    if not query_terms:
        return 0.0
    matches = sum(1 for term in query_terms if term in haystack)
    title_boost = sum(1 for term in query_terms if term in (title or "").lower())
    return round((matches / len(query_terms)) + (title_boost * 0.25), 4)


def _shape_result(row: Any, score: float, method: str) -> dict[str, Any]:
    metadata = _parse_metadata(getattr(row, "metadata_json", None))
    return {
        "source_type": row.source_type,
        "source_id": str(row.source_id),
        "ticket_id": getattr(row, "ticket_id", None),
        "title": row.title or "",
        "snippet": ((row.body or "")[:700]).strip(),
        "score": round(float(score or 0), 4),
        "match_method": method,
        "metadata": metadata,
    }


def _parse_metadata(raw_metadata: Any) -> dict[str, Any]:
    if not raw_metadata:
        return {}
    try:
        return json.loads(raw_metadata)
    except Exception:
        return {}


async def retrieve_ticket_context(
    db: Session,
    query: str,
    *,
    limit: int = 8,
    source_types: Optional[list[str]] = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 8), 30))
    source_types = source_types or ["ticket", "comment", "kb_article"]
    ready = ticket_vector_store_ready(db)
    if not ready:
        return _fallback_from_core_tables(db, query, limit)

    if embedding_enabled():
        query_embedding = await _embed_text(query)
        if query_embedding:
            try:
                rows = db.execute(
                    text(
                        """
                        SELECT source_type, source_id, ticket_id, title, body, metadata_json,
                               1 - (embedding <=> CAST(:embedding AS vector)) AS score
                        FROM ticket_search_documents
                        WHERE embedding IS NOT NULL
                          AND source_type = ANY(:source_types)
                        ORDER BY embedding <=> CAST(:embedding AS vector)
                        LIMIT :limit
                        """
                    ),
                    {
                        "embedding": _vector_literal(query_embedding),
                        "source_types": source_types,
                        "limit": limit,
                    },
                ).all()
                return {
                    "query": query,
                    "match_method": "vector",
                    "results": [_shape_result(row, row.score, "vector") for row in rows],
                }
            except Exception as e:
                db.rollback()
                print(f"[vectors] vector search failed, using keyword fallback: {e}")

    terms = _terms(query)
    rows = db.execute(
        text(
            """
            SELECT source_type, source_id, ticket_id, title, body, metadata_json
            FROM ticket_search_documents
            WHERE source_type = ANY(:source_types)
            ORDER BY updated_at DESC
            LIMIT 500
            """
        ),
        {"source_types": source_types},
    ).all()
    scored = []
    for row in rows:
        metadata = _parse_metadata(getattr(row, "metadata_json", None))
        score = _keyword_score(terms, row.title, row.body, metadata)
        scored.append(_shape_result(row, score, "keyword"))
    scored = [item for item in scored if item["score"] > 0]
    scored.sort(key=lambda item: item["score"], reverse=True)
    return {"query": query, "match_method": "keyword", "results": scored[:limit]}


def _fallback_from_core_tables(db: Session, query: str, limit: int) -> dict[str, Any]:
    terms = _terms(query)
    candidates: list[dict[str, Any]] = []
    for ticket in db.query(TicketRecord).order_by(TicketRecord.updated_at.desc()).limit(500).all():
        metadata = _ticket_metadata(ticket)
        score = _keyword_score(terms, ticket.subject, ticket.description or "", metadata)
        if score > 0:
            candidates.append(
                {
                    "source_type": "ticket",
                    "source_id": ticket.id,
                    "ticket_id": ticket.id,
                    "title": ticket.subject,
                    "snippet": (ticket.description or "")[:700],
                    "score": score,
                    "match_method": "keyword",
                    "metadata": metadata,
                }
            )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return {"query": query, "match_method": "keyword", "results": candidates[:limit]}
