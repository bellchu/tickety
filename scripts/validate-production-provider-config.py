#!/usr/bin/env python3
"""Fail closed unless both production runtimes resolve a usable provider.

Input is one secret-free JSON summary per line, produced inside the running
backend and worker containers by ``summarize-effective-provider-config.py``.
This deliberately validates the effective setting layer after authenticated
database overrides have been applied; Compose environment alone is not the
runtime source of truth.
"""

from __future__ import annotations

import copy
import json
import sys
from urllib.parse import urlsplit


RUNTIME_SERVICES = ("backend", "worker")
REQUIRED_TICKET_INCLUDES = frozenset({"stats", "requester"})
PLACEHOLDER_DOMAINS = frozenset({
    "demo.freshservice.com",
    "example.freshservice.com",
    "yourdomain.freshservice.com",
})


def _normalized_domain(value: object) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower().rstrip(".")


def validate_provider_config(summaries: list[dict]) -> None:
    if not isinstance(summaries, list):
        raise ValueError("effective runtime summaries must be a list")
    by_service: dict[str, dict] = {}
    for summary in summaries:
        if not isinstance(summary, dict):
            raise ValueError("effective runtime summary must be an object")
        service = str(summary.get("service") or "").strip()
        if service not in RUNTIME_SERVICES:
            raise ValueError(f"unexpected runtime service {service or '<missing>'}")
        if service in by_service:
            raise ValueError(f"duplicate runtime summary for {service}")
        by_service[service] = summary
    missing_services = set(RUNTIME_SERVICES) - set(by_service)
    if missing_services:
        raise ValueError(
            "missing effective runtime summary for "
            + ", ".join(sorted(missing_services))
        )

    normalized: dict[str, dict] = {}
    for service in RUNTIME_SERVICES:
        summary = by_service[service]
        app_mode = str(summary.get("app_mode") or "").strip().lower()
        if app_mode != "production":
            raise ValueError(f"{service} APP_MODE must be production")
        provider = str(summary.get("provider") or "").strip().lower()
        if provider != "freshservice":
            raise ValueError(f"{service} must resolve the Freshservice provider")

        domain = _normalized_domain(summary.get("domain"))
        if (
            not domain
            or domain in PLACEHOLDER_DOMAINS
            or not domain.endswith(".freshservice.com")
        ):
            raise ValueError(
                f"{service} must resolve the configured production Freshservice account"
            )

        authentication = {
            str(value).strip().lower()
            for value in summary.get("authentication", [])
            if str(value).strip()
        }
        if not authentication.intersection({"api_key", "oauth"}):
            raise ValueError(
                f"{service} requires an effective Freshservice API key or OAuth token"
            )

        includes = {
            str(value).strip().lower()
            for value in summary.get("ticket_includes", [])
            if str(value).strip()
        }
        missing_includes = REQUIRED_TICKET_INCLUDES - includes
        if missing_includes:
            raise ValueError(
                f"{service} effective ticket includes must contain "
                + ", ".join(sorted(missing_includes))
            )
        normalized[service] = {
            "app_mode": app_mode,
            "provider": provider,
            "domain": domain,
            "authentication": authentication,
            "ticket_includes": includes,
        }

    backend = normalized["backend"]
    worker = normalized["worker"]
    for key in ("app_mode", "provider", "domain", "authentication", "ticket_includes"):
        if backend[key] != worker[key]:
            raise ValueError(
                f"backend and worker effective Freshservice configuration differ for {key}"
            )


def _self_test() -> None:
    # Models production's authenticated DB override path: Compose can omit
    # these values while both processes still resolve approved settings.
    effective = {
        "app_mode": "production",
        "provider": "freshservice",
        "domain": "support.freshservice.com",
        "authentication": ["api_key"],
        "ticket_includes": ["requester", "stats"],
    }
    good = [
        {"service": service, **copy.deepcopy(effective)}
        for service in RUNTIME_SERVICES
    ]
    validate_provider_config(good)

    mutations = (
        (0, "app_mode", "demo"),
        (0, "provider", ""),
        (0, "domain", "yourdomain.freshservice.com"),
        (0, "authentication", []),
        (0, "ticket_includes", ["requester"]),
        (1, "domain", "other.freshservice.com"),
    )
    for index, key, value in mutations:
        candidate = copy.deepcopy(good)
        candidate[index][key] = value
        try:
            validate_provider_config(candidate)
        except ValueError:
            continue
        raise AssertionError(f"self-test accepted invalid effective {key}")

    for candidate in (good[:1], good + [copy.deepcopy(good[0])]):
        try:
            validate_provider_config(candidate)
        except ValueError:
            continue
        raise AssertionError("self-test accepted incomplete or duplicate summaries")
    print("Production Freshservice effective-runtime validator self-test passed.")


def _read_summaries() -> list[dict]:
    summaries = []
    for line in sys.stdin:
        if not line.strip():
            continue
        summaries.append(json.loads(line))
    return summaries


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        _self_test()
        return 0
    if sys.argv[1:]:
        raise SystemExit("usage: validate-production-provider-config.py [--self-test]")
    try:
        validate_provider_config(_read_summaries())
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SystemExit(
            f"Production Freshservice configuration rejected: {exc}"
        ) from exc
    print("Production Freshservice effective runtime configuration verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
