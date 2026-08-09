#!/usr/bin/env python3
"""Create, validate, and conditionally activate a Freshservice trial binding.

The script reads provider credentials from the Tickety process environment and
never prints the account host, API key, cookies, or provider response bodies.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

from app.backend.integrations.freshservice import FreshserviceAdapter


def _required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def _freshservice_domain() -> str:
    configured = (os.getenv("FRESHSERVICE_DOMAIN") or "").strip()
    if configured:
        return configured
    # Existing installations may keep non-secret provider settings in the
    # database. Reuse that authoritative setting without printing it.
    from app.backend.database import SessionLocal, SettingsRecord

    db = SessionLocal()
    try:
        row = db.query(SettingsRecord).filter(
            SettingsRecord.key == "FRESHSERVICE_DOMAIN"
        ).first()
        configured = str(row.value or "").strip() if row else ""
    finally:
        db.close()
    if not configured:
        raise RuntimeError("Freshservice account domain is not configured")
    return configured


def _request(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    response = client.request(method, path.lstrip("/"), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"Tickety API request failed: {method} {path} status={response.status_code}")
    return response


def main() -> int:
    email = _required("POC_ADMIN_EMAIL")
    password = _required("POC_ADMIN_PASSWORD")
    raw_domain = _freshservice_domain()
    host = FreshserviceAdapter._normalize_domain(raw_domain).lower().rstrip(".")
    if "." not in host:
        host = f"{host}.freshservice.com"

    base_url = (os.getenv("POC_TICKETY_URL") or "http://127.0.0.1:8000").rstrip("/") + "/"
    origin = (os.getenv("FRONTEND_URL") or "https://tickety.situ.io").rstrip("/")
    with httpx.Client(
        base_url=base_url,
        headers={"Origin": origin},
        follow_redirects=False,
        timeout=30,
    ) as client:
        _request(client, "POST", "/auth/login", json={"email": email, "password": password})
        session_cookies = [
            f"{cookie.name}={cookie.value}"
            for cookie in client.cookies.jar
            if cookie.name.endswith("session")
        ]
        if len(session_cookies) != 1:
            raise RuntimeError("Tickety login did not issue exactly one session cookie")
        # Loopback uses HTTP, so an RFC-compliant client will not automatically
        # return a Secure cookie. Explicitly replay the just-issued opaque
        # cookie only to the configured loopback/API base for this process.
        client.headers["Cookie"] = session_cookies[0]
        bindings = _request(client, "GET", "/admin/integrations/bindings").json().get(
            "bindings", []
        )
        binding = next(
            (
                item
                for item in bindings
                if item.get("provider") == "freshservice"
                and item.get("environment") == "trial"
                and item.get("canonical_account_host") == host
                and item.get("state") not in {"expired", "retired"}
            ),
            None,
        )
        if binding is None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=14)
            binding = _request(
                client,
                "POST",
                "/admin/integrations/bindings",
                json={
                    "provider": "freshservice",
                    "environment": "trial",
                    "canonical_account_host": host,
                    "workspace_ids": [],
                    "credential_reference": "env://freshservice",
                    "expires_at": expires_at.isoformat(),
                },
            ).json()

        binding_id = str(binding["id"])
        capability_statuses: dict[str, str] = {}
        legacy_provider = "unchanged"
        ready = binding.get("state") == "active"
        if not ready:
            validation = _request(
                client,
                "POST",
                f"/admin/integrations/bindings/{binding_id}/validate",
            ).json()
            capability_statuses = {
                name: str(details.get("status") or "unknown")
                for name, details in validation.get("capabilities", {}).items()
            }
            ready = bool(validation.get("ready_for_activation"))
            binding = validation.get("binding") or binding
            if ready:
                binding = _request(
                    client,
                    "POST",
                    f"/admin/integrations/bindings/{binding_id}/activate",
                ).json()
            elif (os.getenv("POC_DISABLE_LEGACY_ON_FAILURE") or "true").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }:
                _request(
                    client,
                    "PUT",
                    "/admin/settings",
                    json={"ITSM_PROVIDER": "standalone"},
                )
                legacy_provider = "standalone"

        print(
            json.dumps(
                {
                    "binding_id": binding_id,
                    "environment": binding.get("environment"),
                    "state": binding.get("state"),
                    "ready_for_activation": ready,
                    "legacy_provider": legacy_provider,
                    "capabilities": capability_statuses,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Freshservice POC activation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
