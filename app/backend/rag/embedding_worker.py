from __future__ import annotations

import asyncio
import math
import os
import random
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text

from ..database import SessionLocal
from ..privacy import configured_secret_values, redact_text
from .config import (
    dimensions,
    embedding_batch_size,
    embedding_lease_seconds,
    scope_key,
    worker_enabled,
    worker_poll_seconds,
)
from .store_v2 import authoritative_source, replace_source_chunks, store_ready


_MAX_ATTEMPTS = 2
_worker_lock = threading.Lock()
_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


async def _embed_texts(inputs: list[str]) -> list[list[float]]:
    if not inputs or len(inputs) > embedding_batch_size():
        raise ValueError("embedding batch size is invalid")
    from litellm import aembedding
    from .. import ticket_vectors
    from ..llm_manager import (
        _release_provider_lease,
        _reserve_provider_capacity,
        _settle_provider_tokens,
        _try_acquire_provider_lease,
        resolve_provider,
    )

    if not ticket_vectors.embedding_enabled():
        raise RuntimeError("embeddings are disabled")
    kwargs = ticket_vectors._embedding_kwargs()
    if not kwargs.get("api_key"):
        raise RuntimeError("embedding provider credentials are unavailable")
    try:
        per_item_max = int(
            os.getenv("TICKET_EMBEDDING_MAX_CHARS", "32000") or "32000"
        )
    except ValueError:
        per_item_max = 32000
    per_item_max = max(4000, min(per_item_max, 120000))
    safe_inputs = [
        redact_text(value, configured_secret_values())[:per_item_max]
        for value in inputs
    ]
    if sum(len(value) for value in safe_inputs) > 120_000:
        raise ValueError("embedding batch exceeds the total character bound")
    model = ticket_vectors.embedding_model()
    provider = resolve_provider(model)
    timeout = ticket_vectors._embedding_timeout()
    deadline = time.monotonic() + timeout
    try:
        concurrency = int(
            os.getenv("LLM_MAX_CONCURRENCY", "4") or "4"
        )
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
        reserved_tokens = _reserve_provider_capacity(
            provider,
            max(1, sum(len(value.encode("utf-8")) for value in safe_inputs)),
        )
        response = await asyncio.wait_for(
            aembedding(input=safe_inputs, timeout=timeout, **kwargs),
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
    if not isinstance(data, (list, tuple)) or len(data) != len(safe_inputs):
        raise ValueError("embedding provider returned a partial batch")

    indexed: list[tuple[int, list[float]]] = []
    for fallback_index, item in enumerate(data):
        raw_index = item.get("index") if isinstance(item, dict) else getattr(item, "index", None)
        index = fallback_index if raw_index is None else int(raw_index)
        raw = item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding", None)
        if not isinstance(raw, (list, tuple)) or len(raw) != dimensions():
            raise ValueError("embedding provider returned a wrong-dimension vector")
        vector = [float(value) for value in raw]
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("embedding provider returned a non-finite vector")
        indexed.append((index, vector))
    indexed.sort(key=lambda item: item[0])
    if [index for index, _vector in indexed] != list(range(len(safe_inputs))):
        raise ValueError("embedding provider returned invalid item indices")
    return [vector for _index, vector in indexed]


def _claim_batch(owner: str, embedding_identity: str) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        if not store_ready(db):
            return []
        # A provider/model/dimension identity rotation never reuses a stale
        # vector. Keep the chunk lexically searchable while it is re-queued.
        db.execute(text("""
            UPDATE ticket_search_chunks_v2
            SET embedding = NULL,
                embedding_identity = NULL,
                embedded_at = NULL,
                embedding_state = 'queued',
                embedding_attempts = 0,
                not_before = CURRENT_TIMESTAMP,
                lease_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = 'embedding_identity_changed',
                updated_at = CURRENT_TIMESTAMP
            WHERE scope_key = :scope_key
              AND embedding_state = 'ready'
              AND embedding_identity IS DISTINCT FROM :embedding_identity
        """), {
            "scope_key": scope_key(),
            "embedding_identity": embedding_identity,
        })
        db.execute(text("""
            UPDATE ticket_search_chunks_v2
            SET embedding_state = CASE
                    WHEN embedding_attempts >= :max_attempts THEN 'dead_letter'
                    ELSE 'queued'
                END,
                lease_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                not_before = CURRENT_TIMESTAMP,
                last_error_code = 'lease_expired',
                updated_at = CURRENT_TIMESTAMP
            WHERE scope_key = :scope_key
              AND embedding_state = 'running'
              AND lease_expires_at <= CURRENT_TIMESTAMP
        """), {"scope_key": scope_key(), "max_attempts": _MAX_ATTEMPTS})
        rows = db.execute(text("""
            SELECT chunk_id, source_type, source_id, section_path, content, content_hash,
                   parent_hash, source_revision
            FROM ticket_search_chunks_v2
            WHERE scope_key = :scope_key
              AND embedding_state = 'queued'
              AND embedding_attempts < :max_attempts
              AND not_before <= CURRENT_TIMESTAMP
            ORDER BY not_before, updated_at, chunk_id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        """), {
            "scope_key": scope_key(),
            "max_attempts": _MAX_ATTEMPTS,
            "batch_size": embedding_batch_size(),
        }).all()
        claimed: list[dict[str, Any]] = []
        lease_expires_at = datetime.utcnow() + timedelta(seconds=embedding_lease_seconds())
        for row in rows:
            lease_id = str(uuid.uuid4())
            updated = db.execute(text("""
                UPDATE ticket_search_chunks_v2
                SET embedding_state = 'running',
                    embedding_attempts = embedding_attempts + 1,
                    lease_id = :lease_id,
                    lease_owner = :lease_owner,
                    lease_expires_at = :lease_expires_at,
                    last_error_code = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE chunk_id = :chunk_id
                  AND embedding_state = 'queued'
                RETURNING embedding_attempts
            """), {
                "chunk_id": row.chunk_id,
                "lease_id": lease_id,
                "lease_owner": owner,
                "lease_expires_at": lease_expires_at,
            }).first()
            if updated:
                claimed.append({
                    **dict(row._mapping),
                    "lease_id": lease_id,
                    "embedding_attempts": int(updated.embedding_attempts),
                })
        db.commit()
        return claimed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _embedding_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _commit_success(row: dict[str, Any], vector: list[float], identity: str) -> bool:
    db = SessionLocal()
    try:
        current = authoritative_source(
            db, row["source_type"], row["source_id"], for_update=True
        )
        if (
            current is None
            or current.parent_hash != row["parent_hash"]
            or current.revision != row["source_revision"]
        ):
            db.rollback()
            replace_source_chunks(
                db, row["source_type"], row["source_id"], force=True
            )
            return False
        result = db.execute(text("""
            UPDATE ticket_search_chunks_v2
            SET embedding = CAST(:embedding AS vector),
                embedding_identity = :embedding_identity,
                embedded_at = CURRENT_TIMESTAMP,
                embedding_state = 'ready',
                lease_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE chunk_id = :chunk_id
              AND content_hash = :content_hash
              AND parent_hash = :parent_hash
              AND source_revision = :source_revision
              AND embedding_state = 'running'
              AND lease_id = :lease_id
              AND lease_expires_at > CURRENT_TIMESTAMP
        """), {
            "embedding": _embedding_literal(vector),
            "embedding_identity": identity,
            "chunk_id": row["chunk_id"],
            "content_hash": row["content_hash"],
            "parent_hash": row["parent_hash"],
            "source_revision": row["source_revision"],
            "lease_id": row["lease_id"],
        })
        db.commit()
        return int(result.rowcount or 0) == 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _commit_failure(row: dict[str, Any], error_code: str) -> None:
    db = SessionLocal()
    try:
        attempts = int(row["embedding_attempts"])
        dead = attempts >= _MAX_ATTEMPTS
        delay = 0 if dead else min(60, (2 ** attempts) + random.uniform(0, 1))
        db.execute(text("""
            UPDATE ticket_search_chunks_v2
            SET embedding_state = :state,
                not_before = :not_before,
                lease_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = :error_code,
                updated_at = CURRENT_TIMESTAMP
            WHERE chunk_id = :chunk_id
              AND embedding_state = 'running'
              AND lease_id = :lease_id
        """), {
            "state": "dead_letter" if dead else "queued",
            "not_before": datetime.utcnow() + timedelta(seconds=delay),
            "error_code": error_code[:80],
            "chunk_id": row["chunk_id"],
            "lease_id": row["lease_id"],
        })
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _embed_with_isolation(
    rows: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], list[float]]], list[dict[str, Any]]]:
    try:
        vectors = await _embed_texts([
            "\n".join(
                part for part in (
                    str(row.get("section_path") or "").strip(),
                    str(row["content"]).strip(),
                ) if part
            )
            for row in rows
        ])
        return list(zip(rows, vectors)), []
    except Exception:
        if len(rows) == 1:
            return [], rows
        midpoint = len(rows) // 2
        left, right = await asyncio.gather(
            _embed_with_isolation(rows[:midpoint]),
            _embed_with_isolation(rows[midpoint:]),
        )
        return [*left[0], *right[0]], [*left[1], *right[1]]


async def process_once(owner: str | None = None) -> int:
    from ..ticket_vectors import _embedding_identity

    owner = owner or f"rag-worker-{uuid.uuid4()}"
    identity = _embedding_identity()
    rows = await asyncio.to_thread(_claim_batch, owner, identity)
    if not rows:
        return 0
    successes, failures = await _embed_with_isolation(rows)
    for row, vector in successes:
        try:
            await asyncio.to_thread(_commit_success, row, vector, identity)
        except Exception:
            await asyncio.to_thread(_commit_failure, row, "commit_failed")
    for row in failures:
        await asyncio.to_thread(_commit_failure, row, "provider_invalid_item")
    return len(rows)


async def _run_loop(owner: str) -> None:
    while not _stop_event.is_set():
        try:
            processed = await process_once(owner)
        except Exception as exc:
            print(f"[rag-v2-worker] batch failed kind={type(exc).__name__}")
            processed = 0
        if processed == 0:
            await asyncio.to_thread(_stop_event.wait, worker_poll_seconds())


def start_embedding_worker() -> bool:
    global _worker_thread
    if not worker_enabled():
        return False
    from ..ticket_vectors import embedding_enabled

    if not embedding_enabled():
        return False
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return True
        _stop_event.clear()
        owner = f"rag-worker-{uuid.uuid4()}"
        _worker_thread = threading.Thread(
            target=lambda: asyncio.run(_run_loop(owner)),
            name="rag-v2-embedding-worker",
            daemon=True,
        )
        _worker_thread.start()
        return True


def stop_embedding_worker(wait: bool = True) -> None:
    global _worker_thread
    _stop_event.set()
    thread = _worker_thread
    if wait and thread and thread.is_alive():
        thread.join(timeout=max(5, worker_poll_seconds() + 2))
    if thread is None or not thread.is_alive():
        _worker_thread = None
