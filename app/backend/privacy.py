import ipaddress
import re


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


def redact_text(text: str) -> str:
    value = text or ""
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return _IPV6_CANDIDATE.sub(_redact_ipv6, value)


def redact_data(value):
    """Recursively sanitize generated/provider data before persistence/return."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item) for item in value)
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    return value
