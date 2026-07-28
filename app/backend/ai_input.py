"""Helpers for keeping untrusted AI data structurally contained.

Prompt instructions belong in the provider's system message.  These helpers
produce the user message: a canonical JSON object whose text fields are
bounded before serialization, so truncation can never turn data into prompt
syntax.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any


DEFAULT_AI_PROMPT_CHARS = 32_000
MIN_AI_PROMPT_CHARS = 256


class UnsafeAIAdviceError(ValueError):
    """Raised when generated advice contains a narrow, high-risk pattern."""

    def __init__(self, violations: Iterable[str]):
        self.violations = tuple(dict.fromkeys(violations))
        super().__init__(
            "AI advice failed semantic safety validation: "
            + ", ".join(self.violations)
        )


def prompt_char_limit(llm: Any) -> int:
    """Read a manager's prompt limit without trusting mock-like attributes."""
    configured = getattr(llm, "prompt_char_limit", DEFAULT_AI_PROMPT_CHARS)
    if isinstance(configured, bool) or not isinstance(configured, int):
        return DEFAULT_AI_PROMPT_CHARS
    return max(MIN_AI_PROMPT_CHARS, configured)


def canonical_bounded_json(
    text_fields: Mapping[str, Any],
    *,
    max_chars: int = DEFAULT_AI_PROMPT_CHARS,
    field_limits: Mapping[str, int] | None = None,
    fixed_fields: Mapping[str, Any] | None = None,
) -> str:
    """Serialize untrusted text as one bounded, canonical JSON object.

    Every text field receives a sibling ``<name>_truncated`` flag.  Field
    values are shortened *before* JSON serialization.  If escaping or fixed
    metadata would otherwise exceed ``max_chars``, the largest remaining text
    value is shortened again and the object is re-serialized.  The function
    never slices serialized JSON.
    """
    if isinstance(max_chars, bool) or not isinstance(max_chars, int):
        raise TypeError("max_chars must be an integer")
    if max_chars < MIN_AI_PROMPT_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_AI_PROMPT_CHARS}")

    limits = dict(field_limits or {})
    payload: dict[str, Any] = dict(fixed_fields or {})
    values: dict[str, str] = {}
    truncated: dict[str, bool] = {}

    for name, raw_value in text_fields.items():
        if not isinstance(name, str) or not name:
            raise ValueError("text field names must be non-empty strings")
        flag_name = f"{name}_truncated"
        if name in payload or flag_name in payload:
            raise ValueError(f"duplicate AI input field: {name}")
        value = "" if raw_value is None else str(raw_value)
        configured_limit = limits.get(name, len(value))
        if isinstance(configured_limit, bool) or not isinstance(configured_limit, int):
            raise TypeError(f"field limit for {name} must be an integer")
        configured_limit = max(0, configured_limit)
        values[name] = value[:configured_limit]
        truncated[name] = len(value) > configured_limit

    def encode() -> str:
        candidate = dict(payload)
        for field_name, value in values.items():
            candidate[field_name] = value
            candidate[f"{field_name}_truncated"] = truncated[field_name]
        return json.dumps(
            candidate,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    serialized = encode()
    while len(serialized) > max_chars:
        candidates = [name for name, value in values.items() if value]
        if not candidates:
            raise ValueError("fixed AI input metadata exceeds the prompt limit")
        largest = max(
            candidates,
            key=lambda name: len(
                json.dumps(values[name], ensure_ascii=False, separators=(",", ":"))
            ),
        )
        excess = len(serialized) - max_chars
        current = values[largest]
        # Removing at least a quarter makes progress even when one source
        # character expands to several escaped JSON characters.
        remove_chars = max(1, excess, len(current) // 4)
        values[largest] = current[: max(0, len(current) - remove_chars)]
        truncated[largest] = True
        serialized = encode()

    # Defense in depth: callers and tests can rely on parseability, even if
    # this implementation is changed later.
    decoded = json.loads(serialized)
    if not isinstance(decoded, dict):  # pragma: no cover - encode always emits an object
        raise ValueError("AI input must serialize to a JSON object")
    return serialized


_CREDENTIAL_REQUEST_RE = re.compile(
    r"\b(?:ask|send|share|provide|enter|paste|tell|upload|reveal|disclose|"
    r"reply\s+with|confirm|verify)\b"
    r"[^\n.!?]{0,80}\b(?:password|passcode|one[- ]time\s+(?:password|code)|otp|"
    r"mfa\s+code|api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|private\s+key|"
    r"credentials?)\b",
    re.IGNORECASE,
)
_AUTHORITY_URI_RE = re.compile(
    r"\b([a-z][a-z0-9+.-]{1,31})://",
    re.IGNORECASE,
)
_UNSAFE_DIRECT_URI_RE = re.compile(
    r"\b(?:javascript|data|file|vbscript|gopher|smb|ftp|ldap):",
    re.IGNORECASE,
)
_DESTRUCTIVE_COMMANDS = (
    re.compile(
        r"\b(?:sudo\s+)?rm\s+-(?=[a-z]*r)(?=[a-z]*f)[a-z]+\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:sudo\s+)?(?:mkfs(?:\.[a-z0-9]+)?|wipefs)\b", re.IGNORECASE),
    re.compile(r"\bdd\s+\b[^\n]*\bof\s*=\s*/dev/", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:\s*(?:/|$)", re.IGNORECASE),
    re.compile(r"\bdrop\s+(?:database|schema|table)\b", re.IGNORECASE),
    re.compile(r"\bkubectl\s+delete\s+(?:namespace|ns)\b", re.IGNORECASE),
    re.compile(r"\bdocker\s+system\s+prune\b[^\n]*(?:--all|-a)\b", re.IGNORECASE),
    re.compile(
        r"\bremove-item\b[^\n]*(?:-recurse\b[^\n]*-force|-force\b[^\n]*-recurse)",
        re.IGNORECASE,
    ),
)
_ALLOWED_ADVICE_URI_SCHEMES = frozenset()
_DOWNLOAD_AND_EXECUTE_RE = re.compile(
    r"\b(?:download|fetch|curl|wget)\b[^\n.!?]{0,100}"
    r"\b(?:and\s+)?(?:run|execute|install|launch|open)\b",
    re.IGNORECASE,
)
_DISABLE_SECURITY_RE = re.compile(
    r"\b(?:disable|turn\s+off|bypass|remove|uninstall)\b[^\n.!?]{0,80}"
    r"\b(?:mfa|multi[- ]factor|two[- ]factor|2fa|endpoint\s+protection|edr|"
    r"antivirus|anti[- ]virus|firewall|security\s+(?:control|software|agent)|"
    r"certificate\s+validation|tls\s+verification)\b",
    re.IGNORECASE,
)


def _text_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _text_values(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            yield from _text_values(nested)


def semantic_advice_violations(value: Any) -> tuple[str, ...]:
    """Return stable violation codes for dangerous generated advice patterns."""
    violations: list[str] = []
    for text_value in _text_values(value):
        if _CREDENTIAL_REQUEST_RE.search(text_value):
            violations.append("credential_request")
        unsafe_uri = bool(_UNSAFE_DIRECT_URI_RE.search(text_value)) or any(
            match.group(1).lower() not in _ALLOWED_ADVICE_URI_SCHEMES
            for match in _AUTHORITY_URI_RE.finditer(text_value)
        )
        if unsafe_uri:
            violations.append("unsafe_uri_scheme")
        if _DOWNLOAD_AND_EXECUTE_RE.search(text_value):
            violations.append("download_and_execute")
        if _DISABLE_SECURITY_RE.search(text_value):
            violations.append("disable_security_control")
        if any(pattern.search(text_value) for pattern in _DESTRUCTIVE_COMMANDS):
            violations.append("destructive_command")
    return tuple(dict.fromkeys(violations))


def validate_semantic_advice(value: Any) -> Any:
    """Return safe advice unchanged, or raise with non-sensitive reason codes."""
    violations = semantic_advice_violations(value)
    if violations:
        raise UnsafeAIAdviceError(violations)
    return value
