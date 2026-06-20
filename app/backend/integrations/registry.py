import os

from .base import BaseITSMAdapter
from .freshservice import FreshserviceAdapter

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

    def parse_webhook(self, payload, headers):
        return None

    def map_priority(self, external_priority):
        return "P3"

    def map_status(self, external_status):
        return "Open"

    def build_ticket_url(self, external_id):
        return ""


def get_adapter(provider: str = None) -> BaseITSMAdapter:
    provider = provider or os.getenv("ITSM_PROVIDER", "standalone")
    if provider not in _ADAPTERS:
        if provider == "freshservice":
            _ADAPTERS[provider] = FreshserviceAdapter()
        elif provider in ("standalone", "none", ""):
            _ADAPTERS[provider] = StandaloneAdapter()
        else:
            raise ValueError(f"Unknown ITSM provider: {provider}")
    return _ADAPTERS[provider]