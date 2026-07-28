import ipaddress
import os
import re
from collections.abc import Iterable


_SECRET_KEY = (
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"secret[_-]?access[_-]?key|password|passwd|token|secret|authorization)"
)


_REDACTIONS = [
    (
        re.compile(
            r"([\"']?authorization[\"']?\s*[:=]\s*)"
            r"[\"']?(?:bearer|basic)\s+[^\s\"',}\]]+[\"']?",
            re.IGNORECASE,
        ),
        r'\1"[secret]"',
    ),
    (
        re.compile(
            rf"((?:[\"']?{_SECRET_KEY}[\"']?)\s*[:=]\s*)"
            r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,}\]]+)",
            re.IGNORECASE,
        ),
        r'\1"[secret]"',
    ),
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[email]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"), "[phone]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[card]"),
    (re.compile(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+", re.IGNORECASE), "[secret]"),
    (re.compile(r"\bauthorization\s*:\s*(?:bearer|basic)\s+\S+", re.IGNORECASE), "[secret]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[token]"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[secret]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,255}\b"), "[secret]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b"), "[secret]"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,255}\b"), "[secret]"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,255}\b"), "[secret]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        "[private-key]",
    ),
    (
        re.compile(
            r"([?&](?:access_token|api_key|apikey|key|token|secret|password)=)[^&#\s]+",
            re.IGNORECASE,
        ),
        r"\1[secret]",
    ),
]

_IPV6_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_:])(?:[A-Fa-f0-9]{0,4}:){2,7}[A-Fa-f0-9]{0,4}(?![A-Za-z0-9_:])"
)


def _redact_ipv6(match: re.Match) -> str:
    candidate = match.group(0)
    try:
        return "[ip]" if ipaddress.ip_address(candidate).version == 6 else candidate
    except ValueError:
        return candidate


def configured_secret_values() -> tuple[str, ...]:
    """Return every configured deployment secret for exact boundary redaction."""
    from .settings import _PLACEHOLDER_VALUES, _SENSITIVE_KEYS

    values = {
        value
        for key, value in os.environ.items()
        if (
            key in _SENSITIVE_KEYS
            or re.search(r"(?:^|_)(?:API_?KEY|KEY|SECRET|TOKEN|PASSWORD)$", key)
        )
        and value
        and value not in _PLACEHOLDER_VALUES
        and value != "****"
    }
    return tuple(sorted(values, key=len, reverse=True))


def _normalize_exact_secrets(exact_secrets: Iterable[str]) -> tuple[str, ...]:
    """Return unique literal secrets in safest replacement order."""
    return tuple(sorted(
        {
            secret
            for secret in exact_secrets
            if isinstance(secret, str) and secret
        },
        key=len,
        reverse=True,
    ))


def _redact_exact_secrets(text: str, exact_secrets: tuple[str, ...]) -> str:
    value = text or ""
    for secret in exact_secrets:
        value = value.replace(secret, "[secret]")
    return value


def _redact_text(text: str, exact_secrets: tuple[str, ...]) -> str:
    # Provider keys are opaque and need not match a recognizable key format or
    # appear next to a label. Replace their configured values literally before
    # applying the heuristic patterns below.
    value = _redact_exact_secrets(text, exact_secrets)
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return _IPV6_CANDIDATE.sub(_redact_ipv6, value)


def redact_text(text: str, exact_secrets: Iterable[str] = ()) -> str:
    return _redact_text(text, _normalize_exact_secrets(exact_secrets))


def redact_data(value, exact_secrets: Iterable[str] = ()):
    """Recursively sanitize generated/provider data before persistence/return."""
    return _redact_data(value, _normalize_exact_secrets(exact_secrets))


def _redact_data(value, exact_secrets: tuple[str, ...]):
    if isinstance(value, str):
        return _redact_text(value, exact_secrets)
    if isinstance(value, list):
        return [_redact_data(item, exact_secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_data(item, exact_secrets) for item in value)
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            safe_key = (
                _redact_exact_secrets(key, exact_secrets)
                if isinstance(key, str)
                else key
            )
            redacted[safe_key] = _redact_data(item, exact_secrets)
        return redacted
    return value
