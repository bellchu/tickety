import re


_REDACTIONS = [
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[email]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"), "[phone]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[card]"),
    (re.compile(r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+", re.IGNORECASE), "[secret]"),
    (re.compile(r"\bauthorization\s*:\s*(?:bearer|basic)\s+\S+", re.IGNORECASE), "[secret]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[token]"),
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


def redact_text(text: str) -> str:
    value = text or ""
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value
