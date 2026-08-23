import os
import json

from .base import BaseITSMAdapter
from .freshservice import FreshserviceAdapter
from .jira import JiraAdapter

_ADAPTERS = {}


class StandaloneAdapter(BaseITSMAdapter):
    """No-op adapter for standalone mode — Tickety manages tickets internally."""

    provider_name = "standalone"

    async def fetch_new_tickets(self, since=None):
        return []

    async def fetch_updated_tickets(self, since):
        return []

    async def fetch_tickets_since(self, since, max_pages=None):
        return []

    async def fetch_agents(self, max_pages=None):
        return []

    def parse_webhook(self, payload, headers, raw_body=None):
        return None

    def map_priority(self, external_priority):
        return "P3"

    def map_status(self, external_status):
        return "Open"

    def build_ticket_url(self, external_id):
        return ""


def _binding_config(binding) -> dict:
    credential_reference = str(
        getattr(binding, "credential_reference", "env://freshservice") or ""
    )
    if credential_reference != "env://freshservice":
        raise ValueError("Unsupported integration credential reference")
    try:
        workspace_ids = json.loads(getattr(binding, "workspace_ids", "[]") or "[]")
    except (TypeError, ValueError):
        workspace_ids = []
    if not isinstance(workspace_ids, list):
        workspace_ids = []
    return {
        "FRESHSERVICE_DOMAIN": getattr(binding, "canonical_account_host", ""),
        "FRESHSERVICE_WORKSPACE_ID": str(workspace_ids[0]) if workspace_ids else "",
    }


def clear_adapter_cache(binding_id: str | None = None) -> None:
    if binding_id is None:
        _ADAPTERS.clear()
        return
    for key in list(_ADAPTERS):
        if isinstance(key, tuple) and key[0] == binding_id:
            _ADAPTERS.pop(key, None)


def configured_provider() -> str:
    """Resolve the runtime provider with a safe production-sidecar default."""
    provider = (os.getenv("ITSM_PROVIDER") or "").strip().lower()
    if not provider:
        provider = (
            "standalone"
            if (os.getenv("APP_MODE") or "production").strip().lower() == "demo"
            else "freshservice"
        )
    provider = "freshservice" if provider == "external" else provider
    if (
        (os.getenv("APP_MODE") or "production").strip().lower() == "production"
        and provider != "freshservice"
    ):
        raise ValueError(
            "Production Tickety runs only as a read-only Freshservice sidecar"
        )
    return provider


def get_adapter(provider: str = None, *, binding=None) -> BaseITSMAdapter:
    provider = provider or (
        getattr(binding, "provider", None) if binding is not None else None
    ) or configured_provider()
    if provider == "external":
        provider = "freshservice"
    if (
        (os.getenv("APP_MODE") or "production").strip().lower() == "production"
        and provider != "freshservice"
    ):
        raise ValueError(
            "Production Tickety runs only as a read-only Freshservice sidecar"
        )
    cache_key = provider
    config = None
    if binding is not None:
        cache_key = (
            str(getattr(binding, "id", "")),
            provider,
            str(getattr(binding, "environment", "")),
        )
        config = _binding_config(binding)
    if cache_key not in _ADAPTERS:
        if provider == "freshservice":
            _ADAPTERS[cache_key] = FreshserviceAdapter(config=config)
        elif provider == "jira":
            _ADAPTERS[cache_key] = JiraAdapter()
        elif provider in ("standalone", "none", ""):
            _ADAPTERS[cache_key] = StandaloneAdapter()
        else:
            raise ValueError(f"Unknown ITSM provider: {provider}")
    return _ADAPTERS[cache_key]
