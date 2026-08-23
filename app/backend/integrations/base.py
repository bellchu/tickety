from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List, Optional

from ..schema import ExternalTicket, WebhookEvent


class BaseITSMAdapter(ABC):
    provider_name: str = "base"
    access_mode: str = "read_only"
    domain: str = ""
    oauth_access_token: str = ""

    @property
    def oauth_configured(self) -> bool:
        """OAuth is unsupported unless an adapter explicitly implements it."""
        return False

    def capability_manifest(self) -> dict[str, dict[str, Any]]:
        """Declare the one-way sidecar contract shared by every provider.

        Provider records are authoritative. Tickety may import them and store
        local intelligence, but provider mutations are intentionally outside
        the adapter interface.
        """
        return {
            "integration.mode": {"status": "supported", "mode": self.access_mode},
            "ticket.read": {"status": "supported"},
            "agent.read": {"status": "unsupported"},
            "requester.read": {"status": "unsupported"},
            "ticket.create": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.update": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.reply": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.note": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.attachment": {"status": "unsupported", "reason": "read_only_sidecar"},
            "service_request.create": {"status": "unsupported", "reason": "read_only_sidecar"},
            "webhook.ingest": {"status": "supported"},
        }

    async def probe_capabilities(self) -> dict[str, dict[str, Any]]:
        """Return observed capabilities; adapters should override live probes."""
        return self.capability_manifest()

    @abstractmethod
    async def fetch_new_tickets(self, since: Optional[datetime] = None) -> List[ExternalTicket]:
        ...

    @abstractmethod
    async def fetch_updated_tickets(self, since: datetime) -> List[ExternalTicket]:
        ...

    async def fetch_tickets_since(self, since: Optional[datetime], max_pages: Optional[int] = None) -> List[ExternalTicket]:
        """Full paginated fetch of every ticket updated since `since`.
        Adapters that support pagination should override this; the default
        falls back to the single-page incremental fetch."""
        return await self.fetch_new_tickets(since=since)

    async def fetch_agents(self, max_pages: Optional[int] = None) -> List[dict]:
        return []

    async def fetch_external_users(self, max_pages: Optional[int] = None) -> List[dict]:
        """Return provider identities as read-only directory records."""
        agents = await self.fetch_agents(max_pages=max_pages)
        return [{**agent, "user_type": "agent"} for agent in agents]

    @abstractmethod
    def parse_webhook(
        self,
        payload: dict,
        headers: dict,
        raw_body: bytes | None = None,
    ) -> Optional[WebhookEvent]:
        ...

    @abstractmethod
    def map_priority(self, external_priority) -> str:
        ...

    @abstractmethod
    def map_status(self, external_status) -> str:
        ...

    @abstractmethod
    def build_ticket_url(self, external_id: str) -> str:
        ...
