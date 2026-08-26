"""Deterministic, identity-minimizing inputs for resolver routing."""

from __future__ import annotations

import os
import re
import hashlib
import json
from email.utils import getaddresses
from typing import Literal


BusinessContext = Literal["ALMO", "JAM", "UNKNOWN"]

_DOMAIN_ENV_SPLIT_RE = re.compile(r"[\s,;]+")
_ASCII_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _normalize_domain(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().casefold()
    if candidate.startswith("@"):
        candidate = candidate[1:]
    candidate = candidate.rstrip(".")
    if not candidate or len(candidate) > 253:
        return None
    if any(character in candidate for character in ("@", "/", "\\", ":")):
        return None
    try:
        candidate = candidate.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        return None
    labels = candidate.split(".")
    if len(labels) < 2 or any(
        not _ASCII_DOMAIN_LABEL_RE.fullmatch(label) for label in labels
    ):
        return None
    return candidate


def _requester_domain(requester_email: object) -> str | None:
    if not isinstance(requester_email, str):
        return None
    value = requester_email.strip()
    # Do not silently select one address from a list.
    if not value or "\n" in value or "\r" in value or ";" in value:
        return None
    parsed_addresses = getaddresses([value])
    if len(parsed_addresses) != 1:
        return None
    _, address = parsed_addresses[0]
    if address.count("@") != 1:
        return None
    local_part, domain = address.rsplit("@", 1)
    if not local_part or any(character.isspace() for character in local_part):
        return None
    return _normalize_domain(domain)


def _configured_domains(environment_name: str) -> frozenset[str]:
    configured: set[str] = set()
    for candidate in _DOMAIN_ENV_SPLIT_RE.split(os.getenv(environment_name, "")):
        normalized = _normalize_domain(candidate)
        if normalized:
            configured.add(normalized)
    return frozenset(configured)


def _domain_matches(domain: str, configured_domain: str) -> bool:
    """Match a domain itself or a subdomain only at a DNS-label boundary."""
    return domain == configured_domain or domain.endswith(f".{configured_domain}")


def routing_business_context(requester_email: object) -> BusinessContext:
    """Map a requester email to a non-identifying, allowlisted context hint.

    No substring heuristics are used: an arbitrary domain containing ``almo``
    or ``jam`` remains unknown. Conflicting configuration also fails closed.
    """
    domain = _requester_domain(requester_email)
    if domain is None or _domain_matches(domain, "nexora.com"):
        return "UNKNOWN"

    almo_match = any(
        _domain_matches(domain, configured)
        for configured in _configured_domains("AI_ROUTING_ALMO_EMAIL_DOMAINS")
    )
    jam_match = any(
        _domain_matches(domain, configured)
        for configured in _configured_domains("AI_ROUTING_JAM_EMAIL_DOMAINS")
    )
    if almo_match == jam_match:
        return "UNKNOWN"
    return "ALMO" if almo_match else "JAM"


def routing_policy_fingerprint() -> str:
    """Return an opaque version for the configured domain-context policy."""
    policy = {
        "version": "routing-context-v1",
        "shared_domains": ["nexora.com"],
        "almo_domains": sorted(_configured_domains("AI_ROUTING_ALMO_EMAIL_DOMAINS")),
        "jam_domains": sorted(_configured_domains("AI_ROUTING_JAM_EMAIL_DOMAINS")),
    }
    encoded = json.dumps(
        policy,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
