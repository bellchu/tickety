#!/usr/bin/env python3
"""Emit a secret-free summary of one process's effective provider settings."""

from __future__ import annotations

import json
import sys


RUNTIME_SERVICES = frozenset({"backend", "worker"})
PLACEHOLDER_CREDENTIALS = frozenset({
    "",
    "dummy-key",
    "your-key-here",
    "your-provider-api-key",
})


def _credential_is_set(value: object) -> bool:
    return str(value or "").strip() not in PLACEHOLDER_CREDENTIALS


def summarize(service: str) -> dict:
    if service not in RUNTIME_SERVICES:
        raise ValueError("service must be backend or worker")

    # The host streams this script into the current container so the gate uses
    # that service's production database and environment before a new image is
    # built. Authenticated DB overrides are resolved by the same shared loader
    # used at backend and worker startup.
    from app.backend import settings as settings_module
    from app.backend.integrations.registry import configured_provider, get_adapter

    settings_module.load_settings_into_env()
    provider = configured_provider()
    adapter = get_adapter(provider)
    authentication = []
    if _credential_is_set(getattr(adapter, "api_key", "")):
        authentication.append("api_key")
    if _credential_is_set(getattr(adapter, "oauth_access_token", "")):
        authentication.append("oauth")
    includes = sorted({
        value.strip().lower()
        for value in str(getattr(adapter, "ticket_includes", "")).split(",")
        if value.strip()
    })
    return {
        "service": service,
        "app_mode": settings_module.app_mode(),
        "provider": provider,
        "domain": str(getattr(adapter, "domain", "")),
        "authentication": authentication,
        "ticket_includes": includes,
    }


def _self_test() -> None:
    assert not _credential_is_set("")
    assert not _credential_is_set("dummy-key")
    assert not _credential_is_set("your-provider-api-key")
    assert _credential_is_set("configured-secret")
    print("Effective provider summary self-test passed.")


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        _self_test()
        return 0
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: summarize-effective-provider-config.py backend|worker|--self-test"
        )
    try:
        summary = summarize(sys.argv[1])
    except (RuntimeError, TypeError, ValueError) as exc:
        raise SystemExit(
            "Production Freshservice effective configuration could not be summarized"
        ) from exc
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
