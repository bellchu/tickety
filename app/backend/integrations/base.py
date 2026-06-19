from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from ..schema import ExternalTicket, WebhookEvent


class BaseITSMAdapter(ABC):
    provider_name: str = "base"

    @abstractmethod
    async def fetch_new_tickets(self, since: Optional[datetime] = None) -> List[ExternalTicket]:
        ...

    @abstractmethod
    async def fetch_updated_tickets(self, since: datetime) -> List[ExternalTicket]:
        ...

    async def fetch_tickets_since(self, since: datetime, max_pages: Optional[int] = None) -> List[ExternalTicket]:
        """Full paginated fetch of every ticket updated since `since`.
        Adapters that support pagination should override this; the default
        falls back to the single-page incremental fetch."""
        return await self.fetch_new_tickets(since=since)

    @abstractmethod
    def parse_webhook(self, payload: dict, headers: dict) -> Optional[WebhookEvent]:
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