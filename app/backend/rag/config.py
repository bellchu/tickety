from __future__ import annotations

import os
import re


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
_SCOPE_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,159}")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean")


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw not in {None, ""} else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def scope_key() -> str:
    value = (os.getenv("TICKET_RAG_SCOPE_KEY") or "default").strip()
    if not _SCOPE_RE.fullmatch(value):
        raise ValueError(
            "TICKET_RAG_SCOPE_KEY must contain only letters, digits, '.', '_', ':', or '-'"
        )
    return value


def scope_enabled(value: str) -> bool:
    """Apply a deployment-owned allowlist; no request value reaches this gate."""
    configured = {
        item.strip()
        for item in (os.getenv("TICKET_RAG_V2_SCOPE_ALLOWLIST") or "").split(",")
        if item.strip()
    }
    invalid = sorted(item for item in configured if not _SCOPE_RE.fullmatch(item))
    if invalid:
        raise ValueError("TICKET_RAG_V2_SCOPE_ALLOWLIST contains an invalid scope")
    return value == scope_key() and (not configured or value in configured)


def read_enabled() -> bool:
    # Serving v2 while source replacement is paused would knowingly allow
    # freshness drift. Roll back reads first; write pause then remains safe.
    return (
        _bool("TICKET_RAG_V2_READ_ENABLED")
        and write_enabled()
        and scope_enabled(scope_key())
    )


def write_enabled() -> bool:
    return _bool("TICKET_RAG_V2_WRITE_ENABLED") and scope_enabled(scope_key())


def worker_enabled() -> bool:
    return _bool("TICKET_RAG_V2_WORKER_ENABLED") and write_enabled()


def dimensions() -> int:
    return _bounded_int("TICKET_EMBEDDING_DIMENSIONS", 1536, 1, 4096)


def chunk_target_tokens() -> int:
    return _bounded_int("TICKET_RAG_CHUNK_TARGET_TOKENS", 450, 100, 1000)


def chunk_max_tokens() -> int:
    value = _bounded_int("TICKET_RAG_CHUNK_MAX_TOKENS", 600, 100, 1500)
    if value < chunk_target_tokens():
        raise ValueError("TICKET_RAG_CHUNK_MAX_TOKENS must be at least the target")
    return value


def chunk_overlap_tokens() -> int:
    value = _bounded_int("TICKET_RAG_CHUNK_OVERLAP_TOKENS", 50, 0, 200)
    if value >= chunk_target_tokens():
        raise ValueError("TICKET_RAG_CHUNK_OVERLAP_TOKENS must be below the target")
    return value


def chunker_identity() -> str:
    return (
        f"rag-v2-cl100k-{chunk_target_tokens()}-{chunk_overlap_tokens()}"
    )


def embedding_batch_size() -> int:
    return _bounded_int("TICKET_RAG_EMBED_BATCH_SIZE", 32, 1, 32)


def embedding_lease_seconds() -> int:
    return _bounded_int("TICKET_RAG_EMBED_LEASE_SECONDS", 120, 30, 900)


def worker_poll_seconds() -> int:
    return _bounded_int("TICKET_RAG_WORKER_POLL_SECONDS", 2, 1, 60)


def query_cache_ttl_seconds() -> int:
    return _bounded_int("TICKET_RAG_QUERY_CACHE_TTL_SECONDS", 2700, 60, 86400)


def query_cache_max_rows() -> int:
    return _bounded_int("TICKET_RAG_QUERY_CACHE_MAX_ROWS", 50000, 100, 1000000)


def snapshot_ttl_seconds() -> int:
    return _bounded_int("TICKET_RAG_SNAPSHOT_TTL_SECONDS", 86400, 60, 86400)
