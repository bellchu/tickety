from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from .config import (
    chunk_max_tokens,
    chunk_overlap_tokens,
    chunk_target_tokens,
    chunker_identity,
)


_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass(frozen=True)
class Chunk:
    index: int
    section_path: str
    content: str
    content_hash: str


class SourceTooLargeError(ValueError):
    pass


def canonical_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t ]+", " ", line).strip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def canonical_query(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def parent_hash(
    *,
    source_type: str,
    source_id: str,
    title: str,
    body: str,
    metadata: dict[str, Any],
) -> str:
    payload = canonical_json({
        "source_type": source_type,
        "source_id": str(source_id),
        "title": canonical_text(title),
        "body": canonical_text(body),
        "metadata": metadata,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chunk_id(
    scope_key: str,
    source_type: str,
    source_id: str,
    source_parent_hash: str,
    chunk_index: int,
    identity: str | None = None,
) -> str:
    raw = "|".join((
        scope_key,
        source_type,
        str(source_id),
        source_parent_hash,
        str(chunk_index),
        identity or chunker_identity(),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _encoding():
    try:
        import tiktoken
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError(
            "tiktoken is required for deterministic RAG v2 chunking"
        ) from exc
    return tiktoken.get_encoding("cl100k_base")


def _sections(title: str, body: str) -> list[tuple[str, str]]:
    clean_title = canonical_text(title)
    clean_body = canonical_text(body)
    if not clean_body:
        return [(clean_title, clean_title)] if clean_title else []
    matches = list(_HEADING_RE.finditer(clean_body))
    if not matches:
        return [(clean_title, clean_body)]
    sections: list[tuple[str, str]] = []
    prefix = clean_body[: matches[0].start()].strip()
    if prefix:
        sections.append((clean_title, prefix))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(clean_body)
        heading = canonical_text(match.group(2))[:500]
        path = " > ".join(item for item in (clean_title, heading) if item)
        content = clean_body[start:end].strip()
        if content:
            sections.append((path, content))
    return sections


def _natural_units(text: str) -> Iterable[str]:
    for paragraph in _PARAGRAPH_RE.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        yield from (part.strip() for part in _SENTENCE_RE.split(paragraph) if part.strip())


def _token_windows(tokens: list[int], maximum: int, overlap: int) -> Iterable[list[int]]:
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + maximum)
        yield tokens[start:end]
        if end == len(tokens):
            break
        start = max(start + 1, end - overlap)


def chunk_source(
    title: str,
    body: str,
    *,
    max_chunks: int,
    target_tokens: int | None = None,
    maximum_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[Chunk]:
    encoder = _encoding()
    target = target_tokens or chunk_target_tokens()
    maximum = maximum_tokens or chunk_max_tokens()
    overlap = chunk_overlap_tokens() if overlap_tokens is None else overlap_tokens
    if not 1 <= target <= maximum or not 0 <= overlap < target:
        raise ValueError("invalid chunk token bounds")

    packed: list[tuple[str, list[int]]] = []
    for section_path, section in _sections(title, body):
        current: list[int] = []
        for unit in _natural_units(section):
            unit_tokens = encoder.encode(unit)
            if len(unit_tokens) > maximum:
                if current:
                    packed.append((section_path, current))
                    current = []
                packed.extend(
                    (section_path, window)
                    for window in _token_windows(unit_tokens, maximum, overlap)
                )
                continue
            separator = encoder.encode("\n") if current else []
            if current and len(current) + len(separator) + len(unit_tokens) > target:
                packed.append((section_path, current))
                carry = current[-overlap:] if overlap else []
                current = [*carry, *encoder.encode("\n"), *unit_tokens]
                if len(current) > maximum:
                    packed.append((section_path, current[:maximum]))
                    current = current[maximum - overlap :]
            else:
                current.extend(separator)
                current.extend(unit_tokens)
        if current:
            packed.append((section_path, current))

    if len(packed) > max_chunks:
        raise SourceTooLargeError(
            f"source produces {len(packed)} chunks; maximum is {max_chunks}"
        )
    chunks: list[Chunk] = []
    for index, (section_path, tokens) in enumerate(packed):
        content = canonical_text(encoder.decode(tokens))
        if not content:
            continue
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunks.append(Chunk(index, section_path[:500], content, digest))
    return chunks
