import asyncio
import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .database import KbArticleRecord, SessionLocal, TicketCommentRecord, TicketRecord
from .privacy import configured_secret_values, redact_text


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9._-]{1,}", re.IGNORECASE)
_PORTAL_SOURCE = "portal"
_AUTHORITY_PRIORITY = {
    "external_report": 1,
    "authenticated_report": 2,
    "internal_comment": 3,
    "published_kb": 4,
}
_PER_TICKET_CANDIDATE_LIMIT = 2
_KEYWORD_DOCUMENT_SQL = """
to_tsvector(
    'simple'::regconfig,
    COALESCE(document.title, '') || ' ' ||
    LEFT(COALESCE(document.body, ''), 20000)
)
"""
_KEYWORD_QUERY_SQL = "plainto_tsquery('simple'::regconfig, :keyword_query)"


def _candidate_pool_limits(limit: int) -> tuple[int, int]:
    """Bound ticket/comment work while reserving room for published knowledge."""
    non_kb = min(300, max(40, int(limit) * 8))
    kb = min(100, max(10, int(limit) * 3))
    return non_kb, kb


def _is_portal_ticket(ticket: TicketRecord | None) -> bool:
    return bool(
        ticket
        and (getattr(ticket, "external_source", None) or "").strip().lower()
        == _PORTAL_SOURCE
    )


def _kb_article_approved(article: KbArticleRecord | None) -> bool:
    if not article or article.status != "published" or not article.reviewer_id:
        return False
    return article.author_id is None or article.reviewer_id != article.author_id


def _kb_metadata_approved(metadata: dict[str, Any]) -> bool:
    reviewer_id = metadata.get("reviewer_id")
    author_id = metadata.get("author_id")
    return bool(
        metadata.get("status") == "published"
        and reviewer_id
        and (author_id is None or reviewer_id != author_id)
    )


def _ticket_document_payload(ticket: TicketRecord) -> dict[str, Any]:
    return {
        "source_type": "ticket",
        "source_id": str(ticket.id),
        "ticket_id": str(ticket.id),
        "title": ticket.subject or "",
        "body": ticket.description or "",
        "metadata": _ticket_metadata(ticket),
    }


def _comment_document_payload(comment: TicketCommentRecord) -> dict[str, Any]:
    return {
        "source_type": "comment",
        "source_id": str(comment.id),
        "ticket_id": str(comment.ticket_id),
        "title": f"Ticket comment on {comment.ticket_id}",
        "body": comment.body or "",
        "metadata": {
            "is_private": bool(comment.is_private),
            "author_id": comment.author_id,
            "author_name": comment.author_name,
            "created_at": comment.created_at,
        },
    }


def _kb_document_payload(article: KbArticleRecord) -> dict[str, Any]:
    return {
        "source_type": "kb_article",
        "source_id": str(article.id),
        "ticket_id": None,
        "title": article.title or "",
        "body": article.content or "",
        "metadata": {
            "slug": article.slug,
            "category": article.category,
            "tags": article.tags,
            "status": article.status,
            "author_id": article.author_id,
            "reviewer_id": article.reviewer_id,
            "updated_at": article.updated_at,
        },
    }


def embedding_enabled() -> bool:
    """Whether provider-backed embeddings may be refreshed.

    Demo mode supports embeddings after an admin explicitly enables them, but
    requires authenticated access before a background refresh can send ticket
    content to the configured provider.
    """
    enabled = (os.getenv("TICKET_EMBEDDING_ENABLED", "") or "").strip().lower() in _TRUE_VALUES
    if not enabled:
        return False
    is_demo = (os.getenv("APP_MODE") or "demo").strip().lower() == "demo"
    login_required = (os.getenv("LOGIN_REQUIRED", "") or "").strip().lower() in _TRUE_VALUES
    return not is_demo or login_required


def private_comment_indexing_enabled() -> bool:
    """Private notes stay local unless an operator explicitly opts them in."""
    return (os.getenv("TICKET_INDEX_PRIVATE_COMMENTS", "") or "").strip().lower() in _TRUE_VALUES


def embedding_model() -> str:
    return (os.getenv("TICKET_EMBEDDING_MODEL") or _DEFAULT_EMBEDDING_MODEL).strip()


def _embedding_identity() -> str:
    provider_kwargs = {
        key: value
        for key, value in _embedding_kwargs().items()
        if key not in {"api_key", "access_token", "authorization"}
    }
    payload = json.dumps(
        {
            "version": "embedding-provider-v1",
            "config": provider_kwargs,
            "dimensions": _dimensions(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"embedding-provider-v1:{hashlib.sha256(payload).hexdigest()}"


def _dimensions() -> int:
    try:
        configured = int(os.getenv("TICKET_EMBEDDING_DIMENSIONS", "1536") or "1536")
    except ValueError:
        configured = 1536
    return max(1, min(configured, 4096))


def _minimum_vector_score() -> float:
    try:
        score = float(os.getenv("TICKET_VECTOR_MIN_SCORE", "0.25") or "0.25")
    except ValueError:
        score = 0.25
    return max(-1.0, min(score, 1.0))


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
        api_key = os.getenv("CUSTOM_API_KEY")
        if not api_key:
            return kwargs
        kwargs["api_key"] = api_key
        kwargs["custom_llm_provider"] = os.getenv("CUSTOM_PROVIDER_TYPE") or "openai"
        api_base = os.getenv("TICKET_EMBEDDING_API_BASE") or os.getenv("CUSTOM_API_BASE")
        if not api_base:
            raise ValueError(
                "TICKET_EMBEDDING_API_BASE or CUSTOM_API_BASE is required for "
                "custom embeddings"
            )
        kwargs["api_base"] = api_base
    if kwargs.get("api_base"):
        from .settings import _validate_llm_base_url

        kwargs["api_base"] = _validate_llm_base_url(kwargs["api_base"])
    return {k: v for k, v in kwargs.items() if v}


def _embedding_timeout() -> float:
    try:
        value = float(os.getenv("TICKET_EMBEDDING_TIMEOUT_SECONDS", "30") or "30")
    except ValueError:
        value = 30.0
    return max(5.0, min(value, 120.0))


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
    model = embedding_model()
    kwargs = _embedding_kwargs()
    if not kwargs.get("api_key"):
        return None
    try:
        from litellm import aembedding
        from .llm_manager import (
            _release_provider_lease,
            _reserve_provider_capacity,
            _settle_provider_tokens,
            _try_acquire_provider_lease,
            resolve_provider,
        )

        try:
            max_chars = int(os.getenv("TICKET_EMBEDDING_MAX_CHARS", "32000") or "32000")
        except ValueError:
            max_chars = 32_000
        max_chars = max(4_000, min(max_chars, 120_000))
        safe_input = redact_text(
            text_value, configured_secret_values()
        )[:max_chars]
        provider = resolve_provider(model)
        timeout = _embedding_timeout()
        deadline = time.monotonic() + timeout
        try:
            concurrency = int(os.getenv("LLM_MAX_CONCURRENCY", "4") or "4")
        except ValueError:
            concurrency = 4
        concurrency = max(1, min(concurrency, 32))
        lease = None
        while lease is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError("embedding provider lease wait exceeded deadline")
            lease = _try_acquire_provider_lease(provider, concurrency, int(remaining) + 15)
            if lease is None:
                await asyncio.sleep(min(0.25, remaining))
        reserved_tokens = 0
        response = None
        try:
            # UTF-8 bytes are a conservative tokenizer-independent estimate.
            reserved_tokens = _reserve_provider_capacity(
                provider, max(1, len(safe_input.encode("utf-8")))
            )
            response = await asyncio.wait_for(
                aembedding(input=[safe_input], timeout=timeout, **kwargs),
                timeout=max(0.001, deadline - time.monotonic()),
            )
        finally:
            _release_provider_lease(provider, lease)
        usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
        total_tokens = (
            int((usage or {}).get("total_tokens", 0) or 0)
            if isinstance(usage, dict)
            else int(getattr(usage, "total_tokens", 0) or 0)
        )
        if total_tokens:
            _settle_provider_tokens(provider, reserved_tokens, total_tokens)
        data = response.get("data") if isinstance(response, dict) else getattr(response, "data", None)
        first = data[0] if data else None
        embedding = first.get("embedding") if isinstance(first, dict) else getattr(first, "embedding", None)
        if not embedding:
            return None
        if not isinstance(embedding, (list, tuple)) or len(embedding) > 4096:
            return None
        values = [float(v) for v in embedding]
        if len(values) != _dimensions():
            print(
                f"[vectors] embedding dimension mismatch expected={_dimensions()} actual={len(values)}"
            )
            return None
        return values
    except Exception as e:
        print(f"[vectors] embedding failed kind={type(e).__name__}")
        return None


def _ticket_document_table_exists(db: Session) -> bool:
    if db.bind.dialect.name != "postgresql":
        return False
    try:
        row = db.execute(text("SELECT to_regclass('ticket_search_documents')")).first()
        return bool(row and row[0])
    except Exception:
        return False


def ticket_vector_store_ready(db: Session) -> bool:
    if not _ticket_document_table_exists(db):
        return False
    try:
        row = db.execute(text(
            """
            SELECT to_regclass('ticket_search_documents') AS relation,
                   format_type(a.atttypid, a.atttypmod) AS embedding_type
            FROM pg_attribute a
            WHERE a.attrelid = to_regclass('ticket_search_documents')
              AND a.attname = 'embedding'
              AND NOT a.attisdropped
            """
        )).first()
        if not row or not row.relation:
            return False
        match = re.fullmatch(r"vector\((\d+)\)", str(row.embedding_type or ""))
        if not match or int(match.group(1)) != _dimensions():
            print(
                f"[vectors] disabled: configured dimensions={_dimensions()} "
                f"database_type={getattr(row, 'embedding_type', None)}"
            )
            return False
        return True
    except Exception:
        return False


def purge_private_comment_documents(db: Session) -> int:
    if private_comment_indexing_enabled() or not _ticket_document_table_exists(db):
        return 0
    result = db.execute(text(
        """
        DELETE FROM ticket_search_documents AS document
        WHERE document.source_type = 'comment'
          AND EXISTS (
              SELECT 1
              FROM ticket_comments AS source_comment
              WHERE CAST(source_comment.id AS text) = document.source_id
                AND COALESCE(source_comment.is_private, false) = true
          )
        """
    ))
    db.commit()
    return int(result.rowcount or 0)


def purge_portal_ticket_documents(db: Session) -> int:
    """Remove every derived document attached to an untrusted portal ticket."""
    if not _ticket_document_table_exists(db):
        return 0
    result = db.execute(text(
        """
        DELETE FROM ticket_search_documents
        WHERE ticket_id IN (
            SELECT id
            FROM tickets
            WHERE LOWER(COALESCE(external_source, '')) = 'portal'
        )
        """
    ))
    db.commit()
    return int(result.rowcount or 0)


def purge_unapproved_kb_documents(db: Session) -> int:
    """Remove KB artifacts whose current source lacks independent approval."""
    if not _ticket_document_table_exists(db):
        return 0
    result = db.execute(text(
        """
        DELETE FROM ticket_search_documents AS document
        WHERE document.source_type = 'kb_article'
          AND NOT EXISTS (
              SELECT 1
              FROM kb_articles AS source_article
              WHERE source_article.id = document.source_id
                AND source_article.status = 'published'
                AND source_article.reviewer_id IS NOT NULL
                AND (
                    source_article.author_id IS NULL
                    OR source_article.reviewer_id <> source_article.author_id
                )
          )
        """
    ))
    db.commit()
    return int(result.rowcount or 0)


def _delete_source_document(
    db: Session,
    source_type: str,
    source_id: str,
    *,
    expected_content_hash: Optional[str] = None,
) -> None:
    hash_predicate = (
        " AND content_hash = :expected_content_hash"
        if expected_content_hash is not None
        else ""
    )
    params = {"source_type": source_type, "source_id": source_id}
    if expected_content_hash is not None:
        params["expected_content_hash"] = expected_content_hash
    db.execute(
        text(
            "DELETE FROM ticket_search_documents "
            "WHERE source_type = :source_type AND source_id = :source_id"
            + hash_predicate
        ),
        params,
    )


def _authoritative_document_snapshot(
    db: Session,
    source_type: str,
    source_id: str,
    *,
    for_update: bool,
) -> Optional[dict[str, Any]]:
    """Rebuild a document solely from its current authoritative source row.

    Search rows are derived artifacts.  They must never decide whether a KB
    article is published, a comment is private, or a ticket is portal-originated.
    """
    if source_type == "ticket":
        query = db.query(TicketRecord).filter(TicketRecord.id == source_id)
        if for_update:
            query = query.populate_existing().with_for_update()
        ticket = query.first()
        if not ticket or _is_portal_ticket(ticket):
            return None
        return _ticket_document_payload(ticket)

    if source_type == "comment":
        try:
            numeric_source_id = int(source_id)
        except (TypeError, ValueError):
            return None
        query = db.query(TicketCommentRecord).filter(
            TicketCommentRecord.id == numeric_source_id
        )
        if for_update:
            query = query.populate_existing().with_for_update()
        comment = query.first()
        if not comment:
            return None
        ticket_query = db.query(TicketRecord).filter(
            TicketRecord.id == comment.ticket_id
        )
        if for_update:
            ticket_query = ticket_query.populate_existing().with_for_update()
        parent_ticket = ticket_query.first()
        if not parent_ticket or _is_portal_ticket(parent_ticket):
            return None
        if comment.is_private and not private_comment_indexing_enabled():
            return None
        return _comment_document_payload(comment)

    if source_type == "kb_article":
        query = db.query(KbArticleRecord).filter(KbArticleRecord.id == source_id)
        if for_update:
            query = query.populate_existing().with_for_update()
        article = query.first()
        if not _kb_article_approved(article):
            return None
        return _kb_document_payload(article)

    return None


def _row_current(db: Session, source_type: str, source_id: str, content_hash: str) -> bool:
    if not ticket_vector_store_ready(db):
        return False
    row = db.execute(
        text(
            """
            SELECT embedding IS NOT NULL AS has_embedding, embedding_model
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
    return (
        bool(row.has_embedding) and row.embedding_model == _embedding_identity()
    ) or not embedding_enabled()


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
    verify_source: bool = False,
) -> bool:
    if not ticket_vector_store_ready(db):
        return False

    title = (title or "").strip()
    body = (body or "").strip()
    content_hash = _document_hash(title, body, metadata)
    if verify_source:
        initial_snapshot = _authoritative_document_snapshot(
            db, source_type, source_id, for_update=False
        )
        if initial_snapshot is None:
            _delete_source_document(db, source_type, source_id)
            db.commit()
            return False
        initial_hash = _document_hash(
            (initial_snapshot["title"] or "").strip(),
            (initial_snapshot["body"] or "").strip(),
            initial_snapshot["metadata"],
        )
        if initial_hash != content_hash:
            _delete_source_document(
                db,
                source_type,
                source_id,
                expected_content_hash=content_hash,
            )
            db.commit()
            return False
    current = not force and _row_current(db, source_type, source_id, content_hash)
    # End the read transaction before awaiting an external embedding provider.
    db.commit()
    if current:
        if verify_source:
            current_snapshot = _authoritative_document_snapshot(
                db, source_type, source_id, for_update=True
            )
            if current_snapshot is None:
                _delete_source_document(db, source_type, source_id)
            else:
                current_hash = _document_hash(
                    (current_snapshot["title"] or "").strip(),
                    (current_snapshot["body"] or "").strip(),
                    current_snapshot["metadata"],
                )
                if current_hash != content_hash:
                    _delete_source_document(
                        db,
                        source_type,
                        source_id,
                        expected_content_hash=content_hash,
                    )
            db.commit()
        return False

    text_for_embedding = "\n".join([title, body]).strip()
    vector = await _embed_text(text_for_embedding)
    if verify_source:
        # The provider call deliberately runs without a database transaction.
        # Re-read and lock the source after it returns so an older delayed writer
        # cannot resurrect an archived KB row or overwrite a newer edit.
        current_snapshot = _authoritative_document_snapshot(
            db, source_type, source_id, for_update=True
        )
        if current_snapshot is None:
            _delete_source_document(db, source_type, source_id)
            db.commit()
            return False
        current_hash = _document_hash(
            (current_snapshot["title"] or "").strip(),
            (current_snapshot["body"] or "").strip(),
            current_snapshot["metadata"],
        )
        if current_hash != content_hash:
            _delete_source_document(
                db,
                source_type,
                source_id,
                expected_content_hash=content_hash,
            )
            db.commit()
            return False
    current_embedding_identity = (
        _embedding_identity() if embedding_enabled() else None
    )
    params = {
        "source_type": source_type,
        "source_id": source_id,
        "ticket_id": ticket_id,
        "title": title,
        "body": body,
        "metadata_json": json.dumps(metadata, default=str),
        "content_hash": content_hash,
        "embedding": _vector_literal(vector) if vector else None,
        "embedding_model": current_embedding_identity if vector else None,
        "current_embedding_identity": current_embedding_identity,
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
                    embedding = CASE
                        WHEN EXCLUDED.content_hash = ticket_search_documents.content_hash
                         AND (
                            :current_embedding_identity IS NULL
                            OR ticket_search_documents.embedding_model = :current_embedding_identity
                         )
                        THEN COALESCE(EXCLUDED.embedding, ticket_search_documents.embedding)
                        ELSE EXCLUDED.embedding
                    END,
                    embedding_model = CASE
                        WHEN EXCLUDED.content_hash = ticket_search_documents.content_hash
                         AND (
                            :current_embedding_identity IS NULL
                            OR ticket_search_documents.embedding_model = :current_embedding_identity
                         )
                        THEN COALESCE(EXCLUDED.embedding_model, ticket_search_documents.embedding_model)
                        ELSE EXCLUDED.embedding_model
                    END,
                    embedded_at = CASE
                        WHEN EXCLUDED.content_hash = ticket_search_documents.content_hash
                         AND (
                            :current_embedding_identity IS NULL
                            OR ticket_search_documents.embedding_model = :current_embedding_identity
                         )
                        THEN COALESCE(EXCLUDED.embedded_at, ticket_search_documents.embedded_at)
                        ELSE EXCLUDED.embedded_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            params,
        )
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"[vectors] document upsert failed kind={type(e).__name__}")
        return False


def _ticket_metadata(ticket: TicketRecord) -> dict[str, Any]:
    return {
        "evidence_version": 2,
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
    # Retrieval evidence must remain independent source material.  Feeding
    # generated summaries/reasoning/plans back into the evidence index lets a
    # model cite its own earlier output as if it were authoritative input.
    if _is_portal_ticket(ticket):
        if _ticket_document_table_exists(db):
            db.execute(
                text("DELETE FROM ticket_search_documents WHERE ticket_id = :ticket_id"),
                {"ticket_id": str(ticket.id)},
            )
            db.commit()
        return False
    payload = _ticket_document_payload(ticket)
    return await _upsert_document(
        db,
        **payload,
        force=force,
        verify_source=True,
    )


async def upsert_comment_document(db: Session, comment: TicketCommentRecord, force: bool = False) -> bool:
    if comment.is_private and not private_comment_indexing_enabled():
        if ticket_vector_store_ready(db) and comment.id is not None:
            db.execute(
                text(
                    "DELETE FROM ticket_search_documents "
                    "WHERE source_type = 'comment' AND source_id = :source_id"
                ),
                {"source_id": str(comment.id)},
            )
            db.commit()
        return False
    return await _upsert_document(
        db,
        **_comment_document_payload(comment),
        force=force,
        verify_source=True,
    )


async def upsert_kb_document(db: Session, article: KbArticleRecord, force: bool = False) -> bool:
    if not _kb_article_approved(article):
        if ticket_vector_store_ready(db):
            db.execute(
                text(
                    "DELETE FROM ticket_search_documents "
                    "WHERE source_type = 'kb_article' AND source_id = :source_id"
                ),
                {"source_id": article.id},
            )
            db.commit()
        return False
    return await _upsert_document(
        db,
        **_kb_document_payload(article),
        force=force,
        verify_source=True,
    )


async def refresh_ticket_documents(
    db: Session,
    ticket: TicketRecord,
    force: bool = False,
    *,
    heartbeat: Optional[Callable[[], Awaitable[None]]] = None,
    deadline_monotonic: Optional[float] = None,
) -> int:
    changed = 0
    if _is_portal_ticket(ticket):
        if _ticket_document_table_exists(db):
            db.execute(
                text("DELETE FROM ticket_search_documents WHERE ticket_id = :ticket_id"),
                {"ticket_id": str(ticket.id)},
            )
            db.commit()
        return 0
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        raise asyncio.TimeoutError("ticket intelligence refresh deadline exceeded")
    if heartbeat:
        await heartbeat()
    if await upsert_ticket_document(db, ticket, force=force):
        changed += 1
    try:
        max_comments = int(os.getenv("TICKET_EMBEDDING_MAX_COMMENTS_PER_REFRESH", "50") or "50")
    except ValueError:
        max_comments = 50
    max_comments = max(0, min(max_comments, 500))
    comments = db.query(TicketCommentRecord).filter(
        TicketCommentRecord.ticket_id == ticket.id
    ).order_by(TicketCommentRecord.created_at.desc()).limit(max_comments).all()
    for comment in comments:
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            raise asyncio.TimeoutError("ticket intelligence refresh deadline exceeded")
        if heartbeat:
            await heartbeat()
        if comment.is_private and not private_comment_indexing_enabled():
            continue
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


def delete_ticket_source_documents(db: Session, ticket_ids: list[str]) -> int:
    """Drop stale ticket metadata without deleting independent comment evidence."""
    if not ticket_ids or not ticket_vector_store_ready(db):
        return 0
    result = db.execute(
        text(
            "DELETE FROM ticket_search_documents "
            "WHERE source_type = 'ticket' AND source_id = ANY(:source_ids)"
        ),
        {"source_ids": list(dict.fromkeys(ticket_ids))},
    )
    return int(result.rowcount or 0)


def _legacy_ticket_backfill_batch(db: Session, limit: int) -> list[TicketRecord]:
    """Return a bounded batch whose successful upsert removes it from this queue.

    Selecting legacy documents first makes repeated backfill calls advance past
    the newest page instead of continually rebuilding the same 500 tickets.
    """
    source_ids = [
        str(source_id)
        for source_id in db.execute(
            text(
                """
                SELECT source_id
                FROM ticket_search_documents
                WHERE source_type = 'ticket'
                  AND COALESCE(metadata_json, '') NOT LIKE :evidence_marker
                ORDER BY source_id
                LIMIT :limit
                """
            ),
            {"limit": limit, "evidence_marker": '%"evidence_version": 2%'},
        ).scalars().all()
    ]
    if not source_ids:
        return []
    tickets_by_id = {
        str(ticket.id): ticket
        for ticket in db.query(TicketRecord).filter(
            TicketRecord.id.in_(source_ids),
            func.lower(func.coalesce(TicketRecord.external_source, ""))
            != _PORTAL_SOURCE,
        ).all()
    }
    missing_source_ids = [
        source_id for source_id in source_ids if source_id not in tickets_by_id
    ]
    if missing_source_ids:
        # These rows are derived search artifacts whose source ticket no longer
        # exists. Removing them prevents an orphaned first page from blocking
        # later legacy tickets forever.
        db.execute(
            text(
                """
                DELETE FROM ticket_search_documents
                WHERE source_type = 'ticket'
                  AND source_id = ANY(:source_ids)
                  AND COALESCE(metadata_json, '') NOT LIKE :evidence_marker
                """
            ),
            {
                "source_ids": missing_source_ids,
                "evidence_marker": '%"evidence_version": 2%',
            },
        )
        db.commit()
    return [
        tickets_by_id[source_id]
        for source_id in source_ids
        if source_id in tickets_by_id
    ]


def _missing_ticket_backfill_batch(db: Session, limit: int) -> list[TicketRecord]:
    source_ids = [
        str(source_id)
        for source_id in db.execute(
            text(
                """
                SELECT source_ticket.id
                FROM tickets AS source_ticket
                LEFT JOIN ticket_search_documents AS document
                  ON document.source_type = 'ticket'
                 AND document.source_id = source_ticket.id
                 AND (
                    :embedding_identity IS NULL
                    OR (
                        document.embedding IS NOT NULL
                        AND document.embedding_model = :embedding_identity
                    )
                )
                WHERE document.source_id IS NULL
                  AND LOWER(COALESCE(source_ticket.external_source, '')) <> 'portal'
                ORDER BY source_ticket.id
                LIMIT :limit
                """
            ),
            {
                "limit": limit,
                "embedding_identity": (
                    _embedding_identity() if embedding_enabled() else None
                ),
            },
        ).scalars().all()
    ]
    if not source_ids:
        return []
    tickets_by_id = {
        str(ticket.id): ticket
        for ticket in db.query(TicketRecord).filter(
            TicketRecord.id.in_(source_ids)
        ).all()
    }
    return [
        tickets_by_id[source_id]
        for source_id in source_ids
        if source_id in tickets_by_id
    ]


def _missing_comment_backfill_batch(
    db: Session,
    limit: int,
    *,
    include_private: bool,
) -> list[TicketCommentRecord]:
    private_filter = (
        ""
        if include_private
        else "AND COALESCE(source_comment.is_private, false) = false"
    )
    source_ids = [
        str(source_id)
        for source_id in db.execute(
            text(
                f"""
                SELECT CAST(source_comment.id AS text)
                FROM ticket_comments AS source_comment
                JOIN tickets AS source_ticket
                  ON source_ticket.id = source_comment.ticket_id
                LEFT JOIN ticket_search_documents AS document
                  ON document.source_type = 'comment'
                 AND document.source_id = CAST(source_comment.id AS text)
                 AND (
                    :embedding_identity IS NULL
                    OR (
                        document.embedding IS NOT NULL
                        AND document.embedding_model = :embedding_identity
                    )
                 )
                WHERE document.source_id IS NULL
                  AND LOWER(COALESCE(source_ticket.external_source, '')) <> 'portal'
                  {private_filter}
                ORDER BY source_comment.id
                LIMIT :limit
                """
            ),
            {
                "limit": limit,
                "embedding_identity": (
                    _embedding_identity() if embedding_enabled() else None
                ),
            },
        ).scalars().all()
    ]
    if not source_ids:
        return []
    comments_by_id = {
        str(comment.id): comment
        for comment in db.query(TicketCommentRecord).filter(
            TicketCommentRecord.id.in_([int(source_id) for source_id in source_ids])
        ).all()
    }
    return [
        comments_by_id[source_id]
        for source_id in source_ids
        if source_id in comments_by_id
    ]


def _missing_kb_backfill_batch(db: Session, limit: int) -> list[KbArticleRecord]:
    source_ids = [
        str(source_id)
        for source_id in db.execute(
            text(
                """
                SELECT source_article.id
                FROM kb_articles AS source_article
                LEFT JOIN ticket_search_documents AS document
                  ON document.source_type = 'kb_article'
                 AND document.source_id = source_article.id
                 AND (
                    :embedding_identity IS NULL
                    OR (
                        document.embedding IS NOT NULL
                        AND document.embedding_model = :embedding_identity
                    )
                 )
                WHERE source_article.status = 'published'
                  AND source_article.reviewer_id IS NOT NULL
                  AND (
                    source_article.author_id IS NULL
                    OR source_article.reviewer_id <> source_article.author_id
                  )
                  AND document.source_id IS NULL
                ORDER BY source_article.id
                LIMIT :limit
                """
            ),
            {
                "limit": limit,
                "embedding_identity": (
                    _embedding_identity() if embedding_enabled() else None
                ),
            },
        ).scalars().all()
    ]
    if not source_ids:
        return []
    articles_by_id = {
        str(article.id): article
        for article in db.query(KbArticleRecord).filter(
            KbArticleRecord.id.in_(source_ids),
            KbArticleRecord.status == "published",
            KbArticleRecord.reviewer_id.isnot(None),
            (
                KbArticleRecord.author_id.is_(None)
                | (KbArticleRecord.reviewer_id != KbArticleRecord.author_id)
            ),
        ).all()
    }
    return [
        articles_by_id[source_id]
        for source_id in source_ids
        if source_id in articles_by_id
    ]


async def backfill_ticket_documents(
    db: Session,
    *,
    limit: int = 200,
    include_comments: bool = True,
    include_kb: bool = True,
    force: bool = False,
) -> dict[str, int | bool]:
    limit = max(1, min(int(limit or 200), 500))
    result: dict[str, int | bool] = {
        "vector_store_ready": ticket_vector_store_ready(db),
        "tickets_seen": 0,
        "comments_seen": 0,
        "kb_seen": 0,
        "documents_changed": 0,
        "portal_documents_purged": 0,
        "unapproved_kb_documents_purged": 0,
    }
    if not result["vector_store_ready"]:
        return result

    if not private_comment_indexing_enabled():
        purge_private_comment_documents(db)
    result["portal_documents_purged"] = purge_portal_ticket_documents(db)
    result["unapproved_kb_documents_purged"] = purge_unapproved_kb_documents(db)

    tickets = _legacy_ticket_backfill_batch(db, limit)
    if not tickets:
        tickets = _missing_ticket_backfill_batch(db, limit)
    if not tickets:
        tickets = db.query(TicketRecord).filter(
            func.lower(func.coalesce(TicketRecord.external_source, ""))
            != _PORTAL_SOURCE
        ).order_by(TicketRecord.updated_at.desc()).limit(limit).all()
    for ticket in tickets:
        result["tickets_seen"] += 1
        if await upsert_ticket_document(db, ticket, force=force):
            result["documents_changed"] += 1

    if include_comments:
        include_private = private_comment_indexing_enabled()
        comments = _missing_comment_backfill_batch(
            db,
            limit,
            include_private=include_private,
        )
        comments_query = db.query(TicketCommentRecord).join(
            TicketRecord, TicketRecord.id == TicketCommentRecord.ticket_id
        ).filter(
            func.lower(func.coalesce(TicketRecord.external_source, ""))
            != _PORTAL_SOURCE
        )
        if not include_private:
            comments_query = comments_query.filter(
                TicketCommentRecord.is_private.is_(False)
            )
        if not comments:
            comments = comments_query.order_by(
                TicketCommentRecord.created_at.desc()
            ).limit(limit).all()
        for comment in comments:
            result["comments_seen"] += 1
            if await upsert_comment_document(db, comment, force=force):
                result["documents_changed"] += 1

    if include_kb:
        articles = _missing_kb_backfill_batch(db, limit)
        if not articles:
            articles = db.query(KbArticleRecord).filter(
                KbArticleRecord.status == "published",
                KbArticleRecord.reviewer_id.isnot(None),
                (
                    KbArticleRecord.author_id.is_(None)
                    | (KbArticleRecord.reviewer_id != KbArticleRecord.author_id)
                ),
            ).order_by(KbArticleRecord.updated_at.desc()).limit(limit).all()
        for article in articles:
            result["kb_seen"] += 1
            if await upsert_kb_document(db, article, force=force):
                result["documents_changed"] += 1

    return result


def ticket_vector_status(db: Session) -> dict[str, Any]:
    ready = ticket_vector_store_ready(db)
    current_embedding_identity = (
        _embedding_identity() if ready and embedding_enabled() else None
    )
    result = {
        "vector_store_ready": ready,
        "embedding_enabled": embedding_enabled(),
        "embedding_model": embedding_model(),
        "embedding_dimensions": _dimensions(),
        "documents": 0,
        "embedded_documents": 0,
        "stale_documents": 0,
        "legacy_ticket_documents": 0,
        "missing_ticket_documents": 0,
        "missing_comment_documents": 0,
        "missing_kb_documents": 0,
    }
    if not ready:
        return result
    row = db.execute(
        text(
            """
            SELECT
                COUNT(*) AS documents,
                COUNT(embedding) FILTER (
                    WHERE :embedding_identity IS NULL
                       OR embedding_model = :embedding_identity
                ) AS embedded_documents,
                COUNT(*) FILTER (
                    WHERE embedding IS NULL
                       OR (
                            :embedding_identity IS NOT NULL
                            AND embedding_model IS DISTINCT FROM :embedding_identity
                       )
                ) AS stale_documents,
                COUNT(*) FILTER (
                    WHERE source_type = 'ticket'
                      AND COALESCE(metadata_json, '') NOT LIKE :evidence_marker
                ) AS legacy_ticket_documents,
                (
                    SELECT COUNT(*)
                    FROM tickets AS source_ticket
                    LEFT JOIN ticket_search_documents AS ticket_document
                      ON ticket_document.source_type = 'ticket'
                     AND ticket_document.source_id = source_ticket.id
                     AND (
                        :embedding_identity IS NULL
                        OR (
                            ticket_document.embedding IS NOT NULL
                            AND ticket_document.embedding_model = :embedding_identity
                        )
                     )
                    WHERE ticket_document.source_id IS NULL
                ) AS missing_ticket_documents,
                (
                    SELECT COUNT(*)
                    FROM ticket_comments AS source_comment
                    LEFT JOIN ticket_search_documents AS comment_document
                      ON comment_document.source_type = 'comment'
                     AND comment_document.source_id = CAST(source_comment.id AS text)
                     AND (
                        :embedding_identity IS NULL
                        OR (
                            comment_document.embedding IS NOT NULL
                            AND comment_document.embedding_model = :embedding_identity
                        )
                     )
                    WHERE comment_document.source_id IS NULL
                      AND (
                        :include_private_comments
                        OR COALESCE(source_comment.is_private, false) = false
                      )
                ) AS missing_comment_documents,
                (
                    SELECT COUNT(*)
                    FROM kb_articles AS source_article
                    LEFT JOIN ticket_search_documents AS kb_document
                      ON kb_document.source_type = 'kb_article'
                     AND kb_document.source_id = source_article.id
                     AND (
                        :embedding_identity IS NULL
                        OR (
                            kb_document.embedding IS NOT NULL
                            AND kb_document.embedding_model = :embedding_identity
                        )
                    )
                    WHERE source_article.status = 'published'
                      AND source_article.reviewer_id IS NOT NULL
                      AND (
                        source_article.author_id IS NULL
                        OR source_article.reviewer_id <> source_article.author_id
                      )
                      AND kb_document.source_id IS NULL
                ) AS missing_kb_documents
            FROM ticket_search_documents
            """
        ),
        {
            "include_private_comments": private_comment_indexing_enabled(),
            "embedding_identity": current_embedding_identity,
            "evidence_marker": '%"evidence_version": 2%',
        },
    ).first()
    if row:
        result.update(
            {
                "documents": int(row.documents or 0),
                "embedded_documents": int(row.embedded_documents or 0),
                "stale_documents": int(row.stale_documents or 0),
                "legacy_ticket_documents": int(
                    row.legacy_ticket_documents or 0
                ),
                "missing_ticket_documents": int(
                    row.missing_ticket_documents or 0
                ),
                "missing_comment_documents": int(
                    row.missing_comment_documents or 0
                ),
                "missing_kb_documents": int(
                    row.missing_kb_documents or 0
                ),
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


def _evidence_authority(source_type: str, metadata: dict[str, Any]) -> str:
    if source_type == "kb_article":
        return "published_kb" if _kb_metadata_approved(metadata) else "unapproved_kb"
    if source_type == "comment":
        return "internal_comment"
    external_source = str(metadata.get("external_source") or "").strip().lower()
    if external_source and external_source != "manual":
        return "external_report"
    return "authenticated_report"


def _provenance(
    source_type: str,
    source_id: str,
    ticket_id: Optional[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    authority = _evidence_authority(source_type, metadata)
    provenance = {
        "authority": authority,
        "source_type": source_type,
        "source_id": str(source_id),
        "ticket_id": str(ticket_id) if ticket_id is not None else None,
    }
    if authority == "external_report":
        provenance["external_source"] = str(metadata.get("external_source") or "")
    return provenance


def _normalized_evidence_key(item: dict[str, Any]) -> str:
    raw = str(item.get("snippet") or item.get("title") or "")
    normalized = unicodedata.normalize("NFKC", raw).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        normalized = (
            f"{item.get('source_type', '')}:{item.get('source_id', '')}"
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _diversify_results(
    results: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Suppress normalized duplicates and cap ticket dominance after ranking."""
    unique: list[dict[str, Any]] = []
    fingerprint_indexes: dict[str, int] = {}
    for item in results:
        fingerprint = _normalized_evidence_key(item)
        existing_index = fingerprint_indexes.get(fingerprint)
        if existing_index is None:
            fingerprint_indexes[fingerprint] = len(unique)
            unique.append(item)
            continue
        existing = unique[existing_index]
        existing_priority = _AUTHORITY_PRIORITY.get(
            str(existing.get("authority") or ""), 0
        )
        candidate_priority = _AUTHORITY_PRIORITY.get(
            str(item.get("authority") or ""), 0
        )
        if candidate_priority > existing_priority:
            unique[existing_index] = item

    diversified: list[dict[str, Any]] = []
    per_ticket: dict[str, int] = {}
    for item in unique:
        ticket_id = item.get("ticket_id")
        if ticket_id is not None:
            ticket_key = str(ticket_id)
            if per_ticket.get(ticket_key, 0) >= 2:
                continue
            per_ticket[ticket_key] = per_ticket.get(ticket_key, 0) + 1
        diversified.append(item)
    selected = diversified[:limit]
    if (
        selected
        and not any(item.get("source_type") == "kb_article" for item in selected)
    ):
        trusted_kb = next(
            (
                item
                for item in diversified[limit:]
                if item.get("authority") == "published_kb"
            ),
            None,
        )
        if trusted_kb is not None:
            selected[-1] = trusted_kb
    return selected


def _shape_result(row: Any, score: float, method: str) -> dict[str, Any]:
    metadata = _parse_metadata(getattr(row, "metadata_json", None))
    source_type = str(row.source_type)
    source_id = str(row.source_id)
    ticket_id = getattr(row, "ticket_id", None)
    if source_type == "ticket" and hasattr(row, "authoritative_external_source"):
        # Retrieval SQL resolves this from the current ticket row. A copied
        # document metadata value must not be able to upgrade external content
        # to an authenticated Tickety report.
        metadata["external_source"] = (
            getattr(row, "authoritative_external_source", None) or ""
        )
    provenance = _provenance(
        source_type, source_id, ticket_id, metadata
    )
    # Compute these values from authoritative fields; never trust similarly
    # named values copied from a search row's metadata JSON.
    metadata["authority"] = provenance["authority"]
    metadata["provenance"] = provenance
    return {
        "source_type": source_type,
        "source_id": source_id,
        "ticket_id": ticket_id,
        "title": row.title or "",
        "snippet": ((row.body or "")[:700]).strip(),
        "score": round(float(score or 0), 4),
        "match_method": method,
        "metadata": metadata,
        "authority": provenance["authority"],
        "provenance": provenance,
    }


def _filter_private_results(
    results: list[dict[str, Any]], include_private_comments: bool
) -> list[dict[str, Any]]:
    return [
        item
        for item in results
        if (
            item.get("source_type") != "kb_article"
            or _kb_metadata_approved(item.get("metadata") or {})
        )
        and (
            item.get("source_type") != "ticket"
            or (item.get("metadata") or {}).get("evidence_version") == 2
        )
        and (
            item.get("source_type") != "ticket"
            or str((item.get("metadata") or {}).get("external_source") or "")
            .strip()
            .lower()
            != _PORTAL_SOURCE
        )
        and (
            item.get("source_type") != "comment"
            or (
                isinstance(
                    (item.get("metadata") or {}).get("is_private"), bool
                )
                and (
                    include_private_comments
                    or (item.get("metadata") or {}).get("is_private") is False
                )
            )
        )
    ]


def _filter_ticket_scope(
    db: Session,
    results: list[dict[str, Any]],
    allowed_assignee_id: Optional[str],
) -> list[dict[str, Any]]:
    """Keep KB evidence plus non-portal tickets assigned to this exact agent."""
    if allowed_assignee_id is None:
        return results
    ticket_ids = {
        str(item["ticket_id"])
        for item in results
        if item.get("ticket_id") and item.get("source_type") != "kb_article"
    }
    if not ticket_ids:
        return [item for item in results if item.get("source_type") == "kb_article"]
    allowed_ids = {
        str(ticket_id)
        for ticket_id, in db.query(TicketRecord.id).filter(
            TicketRecord.id.in_(ticket_ids),
            TicketRecord.assignee_id == allowed_assignee_id,
            func.lower(func.coalesce(TicketRecord.external_source, ""))
            != _PORTAL_SOURCE,
        ).all()
    }
    return [
        item
        for item in results
        if item.get("source_type") == "kb_article"
        or str(item.get("ticket_id")) in allowed_ids
    ]


def _parse_metadata(raw_metadata: Any) -> dict[str, Any]:
    if not raw_metadata:
        return {}
    try:
        decoded = json.loads(raw_metadata)
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


_AUTHORITATIVE_RETRIEVAL_PREDICATE = """
AND (
    (
        document.source_type = 'ticket'
        AND EXISTS (
            SELECT 1
            FROM tickets AS source_ticket
            WHERE source_ticket.id = document.source_id
              AND document.ticket_id = source_ticket.id
              AND LOWER(COALESCE(source_ticket.external_source, '')) <> 'portal'
              AND (
                    :allowed_assignee_id IS NULL
                    OR source_ticket.assignee_id = :allowed_assignee_id
              )
        )
    )
    OR (
        document.source_type = 'comment'
        AND EXISTS (
            SELECT 1
            FROM ticket_comments AS source_comment
            JOIN tickets AS source_ticket
              ON source_ticket.id = source_comment.ticket_id
            WHERE CAST(source_comment.id AS text) = document.source_id
              AND document.ticket_id = source_ticket.id
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
        document.source_type = 'kb_article'
        AND EXISTS (
            SELECT 1
            FROM kb_articles AS source_article
            WHERE source_article.id = document.source_id
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


async def retrieve_ticket_context(
    db: Session,
    query: str,
    *,
    limit: int = 8,
    source_types: Optional[list[str]] = None,
    include_private_comments: bool = False,
    allowed_assignee_id: Optional[str] = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 8), 30))
    source_types = source_types or ["ticket", "comment", "kb_article"]
    ready = ticket_vector_store_ready(db)
    if not ready:
        return _fallback_from_core_tables(
            db, query, limit, source_types, allowed_assignee_id=allowed_assignee_id
        )
    # Do not hold a database connection while awaiting the embedding provider.
    db.commit()
    non_kb_candidate_limit, kb_candidate_limit = _candidate_pool_limits(limit)

    if embedding_enabled():
        query_embedding = await _embed_text(query)
        if query_embedding:
            try:
                common_params = {
                    "embedding": _vector_literal(query_embedding),
                    "embedding_identity": _embedding_identity(),
                    "source_types": source_types,
                    "include_private_comments": include_private_comments,
                    "allowed_assignee_id": allowed_assignee_id,
                    "min_score": _minimum_vector_score(),
                }
                non_kb_rows = db.execute(
                    text(
                        f"""
                        WITH ranked_non_kb AS (
                            SELECT document.source_type, document.source_id,
                                   document.ticket_id, document.title,
                                   document.body, document.metadata_json,
                                   CASE WHEN document.source_type = 'ticket' THEN (
                                       SELECT source_ticket.external_source
                                       FROM tickets AS source_ticket
                                       WHERE source_ticket.id = document.source_id
                                       LIMIT 1
                                   ) END AS authoritative_external_source,
                                   1 - (
                                       document.embedding <=> CAST(:embedding AS vector)
                                   ) AS score,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY document.ticket_id
                                       ORDER BY
                                           document.embedding <=> CAST(:embedding AS vector),
                                           document.updated_at DESC,
                                           document.source_type,
                                           document.source_id
                                   ) AS ticket_candidate_rank
                            FROM ticket_search_documents AS document
                            WHERE document.embedding IS NOT NULL
                              AND document.embedding_model = :embedding_identity
                              AND document.source_type = ANY(:source_types)
                              AND document.source_type IN ('ticket', 'comment')
                              AND 1 - (
                                  document.embedding <=> CAST(:embedding AS vector)
                              ) >= :min_score
                              {_AUTHORITATIVE_RETRIEVAL_PREDICATE}
                        )
                        SELECT source_type, source_id, ticket_id, title, body,
                               metadata_json, authoritative_external_source, score
                        FROM ranked_non_kb
                        WHERE ticket_candidate_rank <= :per_ticket_candidate_limit
                        ORDER BY score DESC, source_type, source_id
                        LIMIT :non_kb_candidate_limit
                        """
                    ),
                    {
                        **common_params,
                        "per_ticket_candidate_limit": _PER_TICKET_CANDIDATE_LIMIT,
                        "non_kb_candidate_limit": non_kb_candidate_limit,
                    },
                ).all()
                kb_rows = db.execute(
                    text(
                        f"""
                        SELECT document.source_type, document.source_id,
                               document.ticket_id, document.title, document.body,
                               document.metadata_json,
                               NULL AS authoritative_external_source,
                               1 - (
                                   document.embedding <=> CAST(:embedding AS vector)
                               ) AS score
                        FROM ticket_search_documents AS document
                        WHERE document.embedding IS NOT NULL
                          AND document.embedding_model = :embedding_identity
                          AND document.source_type = 'kb_article'
                          AND document.source_type = ANY(:source_types)
                          AND 1 - (
                              document.embedding <=> CAST(:embedding AS vector)
                          ) >= :min_score
                          {_AUTHORITATIVE_RETRIEVAL_PREDICATE}
                        ORDER BY document.embedding <=> CAST(:embedding AS vector),
                                 document.updated_at DESC, document.source_id
                        LIMIT :kb_candidate_limit
                        """
                    ),
                    {**common_params, "kb_candidate_limit": kb_candidate_limit},
                ).all()
                rows = [*non_kb_rows, *kb_rows]
                shaped = [_shape_result(row, row.score, "vector") for row in rows]
                shaped.sort(
                    key=lambda item: (
                        float(item.get("score") or 0),
                        _AUTHORITY_PRIORITY.get(str(item.get("authority") or ""), 0),
                    ),
                    reverse=True,
                )
                shaped = _filter_ticket_scope(
                    db,
                    _filter_private_results(shaped, include_private_comments),
                    allowed_assignee_id,
                )
                return {
                    "query": query,
                    "match_method": "vector",
                    "results": _diversify_results(shaped, limit),
                }
            except Exception as e:
                db.rollback()
                print(f"[vectors] vector search failed; using keyword fallback kind={type(e).__name__}")

    terms = set(sorted(_terms(query))[:32])
    if not terms:
        return {"query": query, "match_method": "keyword", "results": []}
    common_params = {
        "source_types": source_types,
        "include_private_comments": include_private_comments,
        "allowed_assignee_id": allowed_assignee_id,
        "keyword_query": " ".join(sorted(terms)),
    }
    non_kb_rows = db.execute(
        text(
            f"""
            WITH matched_non_kb AS MATERIALIZED (
                SELECT document.source_type, document.source_id,
                       document.ticket_id, document.title, document.body,
                       document.metadata_json, document.updated_at,
                       CASE WHEN document.source_type = 'ticket' THEN (
                           SELECT source_ticket.external_source
                           FROM tickets AS source_ticket
                           WHERE source_ticket.id = document.source_id
                           LIMIT 1
                       ) END AS authoritative_external_source,
                       ts_rank_cd(
                           {_KEYWORD_DOCUMENT_SQL}, {_KEYWORD_QUERY_SQL}
                       ) AS keyword_match_score
                FROM ticket_search_documents AS document
                WHERE document.source_type = ANY(:source_types)
                  AND document.source_type IN ('ticket', 'comment')
                  AND {_KEYWORD_DOCUMENT_SQL} @@ {_KEYWORD_QUERY_SQL}
                  {_AUTHORITATIVE_RETRIEVAL_PREDICATE}
            ),
            ranked_non_kb AS (
                SELECT matched_non_kb.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY matched_non_kb.ticket_id
                           ORDER BY matched_non_kb.keyword_match_score DESC,
                                    matched_non_kb.updated_at DESC,
                                    matched_non_kb.source_type,
                                    matched_non_kb.source_id
                       ) AS ticket_candidate_rank
                FROM matched_non_kb
            )
            SELECT source_type, source_id, ticket_id, title, body,
                   metadata_json, authoritative_external_source,
                   keyword_match_score
            FROM ranked_non_kb
            WHERE ticket_candidate_rank <= :per_ticket_candidate_limit
            ORDER BY keyword_match_score DESC, updated_at DESC,
                     source_type, source_id
            LIMIT :non_kb_candidate_limit
            """
        ),
        {
            **common_params,
            "per_ticket_candidate_limit": _PER_TICKET_CANDIDATE_LIMIT,
            "non_kb_candidate_limit": non_kb_candidate_limit,
        },
    ).all()
    kb_rows = db.execute(
        text(
            f"""
            WITH matched_kb AS MATERIALIZED (
                SELECT document.source_type, document.source_id,
                       document.ticket_id, document.title, document.body,
                       document.metadata_json, document.updated_at,
                       NULL AS authoritative_external_source,
                       ts_rank_cd(
                           {_KEYWORD_DOCUMENT_SQL}, {_KEYWORD_QUERY_SQL}
                       ) AS keyword_match_score
                FROM ticket_search_documents AS document
                WHERE document.source_type = 'kb_article'
                  AND document.source_type = ANY(:source_types)
                  AND {_KEYWORD_DOCUMENT_SQL} @@ {_KEYWORD_QUERY_SQL}
                  {_AUTHORITATIVE_RETRIEVAL_PREDICATE}
            )
            SELECT source_type, source_id, ticket_id, title, body,
                   metadata_json, authoritative_external_source,
                   keyword_match_score
            FROM matched_kb
            ORDER BY keyword_match_score DESC, updated_at DESC, source_id
            LIMIT :kb_candidate_limit
            """
        ),
        {**common_params, "kb_candidate_limit": kb_candidate_limit},
    ).all()
    rows = [*non_kb_rows, *kb_rows]
    scored = []
    for row in rows:
        metadata = _parse_metadata(getattr(row, "metadata_json", None))
        score = _keyword_score(terms, row.title, row.body, metadata)
        scored.append(_shape_result(row, score, "keyword"))
    scored = [item for item in scored if item["score"] > 0]
    scored.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            _AUTHORITY_PRIORITY.get(str(item.get("authority") or ""), 0),
        ),
        reverse=True,
    )
    scored = _filter_ticket_scope(
        db,
        _filter_private_results(scored, include_private_comments),
        allowed_assignee_id,
    )
    return {
        "query": query,
        "match_method": "keyword",
        "results": _diversify_results(scored, limit),
    }


def _fallback_from_core_tables(
    db: Session,
    query: str,
    limit: int,
    source_types: list[str],
    *,
    allowed_assignee_id: Optional[str] = None,
) -> dict[str, Any]:
    terms = set(sorted(_terms(query))[:32])
    candidates: list[dict[str, Any]] = []
    if "ticket" not in source_types:
        return {"query": query, "match_method": "keyword", "results": []}
    ticket_query = db.query(TicketRecord)
    ticket_query = ticket_query.filter(
        func.lower(func.coalesce(TicketRecord.external_source, ""))
        != _PORTAL_SOURCE
    )
    if allowed_assignee_id is not None:
        ticket_query = ticket_query.filter(
            TicketRecord.assignee_id == allowed_assignee_id
        )
    for ticket in ticket_query.order_by(TicketRecord.updated_at.desc()).limit(500).all():
        metadata = _ticket_metadata(ticket)
        score = _keyword_score(terms, ticket.subject, ticket.description or "", metadata)
        if score > 0:
            provenance = _provenance(
                "ticket", str(ticket.id), str(ticket.id), metadata
            )
            metadata["authority"] = provenance["authority"]
            metadata["provenance"] = provenance
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
                    "authority": provenance["authority"],
                    "provenance": provenance,
                }
            )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return {
        "query": query,
        "match_method": "keyword",
        "results": _diversify_results(candidates, limit),
    }
