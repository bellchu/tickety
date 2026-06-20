import os
import re
import time
import hmac
import hashlib
import base64
from datetime import datetime
from typing import List, Optional, Tuple

import httpx

from ..schema import ExternalTicket, WebhookEvent
from .base import BaseITSMAdapter

FRESHSERVICE_PRIORITY_MAP = {
    1: "P1",
    2: "P2",
    3: "P3",
    4: "P3",
}

FRESHSERVICE_STATUS_MAP = {
    2: "Open",
    3: "Pending",
    4: "Resolved",
    5: "Closed",
    6: "Escalated",
}


class FreshserviceAdapter(BaseITSMAdapter):
    provider_name = "freshservice"

    def __init__(self):
        self.domain = os.getenv("FRESHSERVICE_DOMAIN", "yourdomain.freshservice.com")
        self.api_key = os.getenv("FRESHSERVICE_API_KEY", "dummy-key")
        self.base_url = f"https://{self.domain}"
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "")

        # OAuth 2.0
        self.oauth_client_id = os.getenv("FRESHSERVICE_OAUTH_CLIENT_ID", "")
        self.oauth_client_secret = os.getenv("FRESHSERVICE_OAUTH_CLIENT_SECRET", "")
        self.oauth_redirect_uri = os.getenv("FRESHSERVICE_OAUTH_REDIRECT_URI", "")
        self.oauth_access_token = os.getenv("FRESHSERVICE_OAUTH_ACCESS_TOKEN", "")
        self.oauth_refresh_token = os.getenv("FRESHSERVICE_OAUTH_REFRESH_TOKEN", "")

    def _auth(self) -> Tuple[str, str] | Tuple[None, None]:
        """Return Basic‑auth tuple (apikey, X) unless OAuth is configured, in
        which case returns (None, None) — _headers() will attach the Bearer token."""
        if self.oauth_access_token:
            return (None, None)
        return (self.api_key, "X")

    def _headers(self) -> dict:
        h: dict = {"Content-Type": "application/json"}
        if self.oauth_access_token:
            h["Authorization"] = f"Bearer {self.oauth_access_token}"
        return h

    @property
    def oauth_configured(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret)

    def oauth_authorization_url(self) -> str:
        """Build the OAuth 2.0 authorisation URL."""
        return (
            f"{self.base_url}/oauth/authorize"
            f"?client_id={self.oauth_client_id}"
            f"&redirect_uri={self.oauth_redirect_uri}"
            f"&response_type=code"
        )

    async def oauth_exchange_code(self, code: str) -> dict:
        """Exchange an OAuth authorisation code for access & refresh tokens."""
        url = f"{self.base_url}/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
            "redirect_uri": self.oauth_redirect_uri,
            "code": code,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def oauth_refresh(self) -> dict:
        """Refresh an expired OAuth access token."""
        url = f"{self.base_url}/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.oauth_client_id,
            "client_secret": self.oauth_client_secret,
            "refresh_token": self.oauth_refresh_token,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    def map_priority(self, external_priority) -> str:
        try:
            return FRESHSERVICE_PRIORITY_MAP.get(int(external_priority), "P3")
        except (ValueError, TypeError):
            return "P3"

    def map_status(self, external_status) -> str:
        try:
            return FRESHSERVICE_STATUS_MAP.get(int(external_status), "Open")
        except (ValueError, TypeError):
            if isinstance(external_status, str):
                return external_status
            return "Open"

    def build_ticket_url(self, external_id: str) -> str:
        return f"{self.base_url}/support/tickets/{external_id}"

    def _parse_ticket(self, raw: dict) -> ExternalTicket:
        return ExternalTicket(
            external_id=str(raw.get("id", "")),
            subject=raw.get("subject", "(no subject)"),
            description=raw.get("description_text", raw.get("description", "")) or "",
            reporter=str(raw.get("requester_id", raw.get("email", ""))),
            priority=self.map_priority(raw.get("priority", 3)),
            status=self.map_status(raw.get("status", 2)),
            assignee_id=str(raw.get("responder_id")) if raw.get("responder_id") else None,
            updated_at=datetime.fromisoformat(raw["updated_at"]) if raw.get("updated_at") else None,
            url=self.build_ticket_url(str(raw.get("id", ""))),
        )

    # ── Rate-limit aware request helper ─────────────────────────────
    #
    # External ITSM rate limit pacing
    # sub-limit on "List All Tickets" (as low as 40/min on the Starter
    # plan). To stay safely under it we (1) pace consecutive list requests
    # with a minimum interval, (2) honour the Retry-After header on 429,
    # and (3) back off when X-RateLimit-Remaining gets low. See
    # https://api.freshservice.com/#intro (Rate limit / Pagination).
    _MIN_INTERVAL_S = float(os.getenv("FRESHSERVICE_MIN_INTERVAL_S", "1.6"))
    _MAX_PAGES = int(os.getenv("FRESHSERVICE_MAX_PAGES", "500"))

    async def _rate_limited_get(self, client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
        """GET with rate-limit pacing + 429 retry. Returns the Response."""
        # Pace: never fire two list requests closer than _MIN_INTERVAL_S.
        elapsed = time.monotonic() - getattr(self, "_last_get_ts", 0.0)
        if elapsed < self._MIN_INTERVAL_S:
            time.sleep(self._MIN_INTERVAL_S - elapsed)

        resp = await client.get(url, auth=self._auth(), headers=self._headers(), params=params)
        self._last_get_ts = time.monotonic()

        # Honor remaining-budget header: if we're close to the limit,
        # wait out the rest of the window so the next call doesn't 429.
        remaining = resp.headers.get("X-Ratelimit-Remaining")
        if remaining is not None:
            try:
                if int(remaining) <= 2:
                    time.sleep(2.0)
            except ValueError:
                pass

        # 429 -> respect Retry-After (seconds) then retry once.
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5") or "5")
            print(f"[External] rate limited; sleeping {retry_after}s")
            time.sleep(retry_after + 0.5)
            self._last_get_ts = time.monotonic()
            resp = await client.get(url, auth=self._auth(), headers=self._headers(), params=params)
        return resp

    @staticmethod
    def _parse_link_next(link_header: Optional[str], base_url: str) -> Optional[str]:
        """Extract the rel=\"next\" URL from a Link header."""
        if not link_header:
            return None
        match = re.search(r'<([^>]+)>;\s*rel="?next"?', link_header)
        if not match:
            return None
        nxt = match.group(1)
        if nxt.startswith("http"):
            return nxt
        return f"{base_url}{nxt}" if nxt.startswith("/") else f"{base_url}/{nxt}"

    async def fetch_new_tickets(self, since: Optional[datetime] = None) -> List[ExternalTicket]:
        """Incremental sync fetch (used by the background worker). Returns the
        first page of tickets updated since `since`. Bounded by a single page
        so the worker stays cheap; use fetch_tickets_since() for full pagination."""
        url = f"{self.base_url}/api/v2/tickets"
        params = {"per_page": 100}
        if since:
            params["updated_since"] = since.isoformat()
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await self._rate_limited_get(client, url, params)
                resp.raise_for_status()
                data = resp.json()
                return [self._parse_ticket(t) for t in data.get("tickets", [])]
        except Exception as e:
            print(f"[External] fetch_new_tickets error: {e}")
            return []

    async def fetch_updated_tickets(self, since: datetime) -> List[ExternalTicket]:
        return await self.fetch_new_tickets(since=since)

    async def fetch_tickets_since(self, since: datetime, max_pages: Optional[int] = None) -> List[ExternalTicket]:
        """Fetch ALL tickets updated since `since`, walking every page while
        respecting provider rate limits. Used by the manual "fetch by days"
        feature. Stops when a page is empty/short or when the Link header has no
        rel="next". `max_pages` defaults to FRESHSERVICE_MAX_PAGES as a safety cap."""
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[ExternalTicket] = []
        page = 1
        url = f"{self.base_url}/api/v2/tickets"
        params = {"per_page": 100, "updated_since": since.isoformat()}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                while page <= cap:
                    params["page"] = page
                    resp = await self._rate_limited_get(client, url, params)
                    if resp.status_code == 429:
                        # _rate_limited_get already retried once; if still 429, abort.
                        print(f"[External] fetch_tickets_since: still rate-limited on page {page}, stopping")
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    tickets = data.get("tickets", [])
                    out.extend(self._parse_ticket(t) for t in tickets)
                    # No next-page link header => last page reached.
                    if not self._parse_link_next(resp.headers.get("link"), self.base_url):
                        break
                    if len(tickets) < 100:
                        break
                    page += 1
            return out
        except Exception as e:
            print(f"[External] fetch_tickets_since error: {e}")
            return out

    async def fetch_agents(self, max_pages: Optional[int] = None) -> List[dict]:
        """Fetch all agents from the provider, walking every page with rate‑limit
        pacing."""
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[dict] = []
        page = 1
        url = f"{self.base_url}/api/v2/agents"
        # Provider API detail: filter to active agents only.
        params: dict = {"per_page": 100, "active": "true"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                while page <= cap:
                    params["page"] = page
                    resp = await self._rate_limited_get(client, url, params)
                    if resp.status_code == 429:
                        print(f"[External] fetch_agents: still rate‑limited on page {page}, stopping")
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    agents = data.get("agents", [])
                    out.extend(agents)
                    if not self._parse_link_next(resp.headers.get("link"), self.base_url):
                        break
                    if len(agents) < 100:
                        break
                    page += 1
            return out
        except Exception as e:
            print(f"[External] fetch_agents error: {e}")
            return out

    def parse_webhook(self, payload: dict, headers: dict) -> Optional[WebhookEvent]:
        signature = headers.get("x-freshservice-webhook-signature", "")
        if self.webhook_secret and signature:
            expected = base64.b64encode(
                hmac.new(self.webhook_secret.encode(), str(payload).encode(), hashlib.sha256).digest()
            ).decode()
            if not hmac.compare_digest(signature, expected):
                print("[External] webhook signature mismatch")
                return None

        ticket_data = payload.get("ticket", payload.get("data", {}))
        ext_id = str(ticket_data.get("id", ""))
        if not ext_id:
            return None

        event_type = payload.get("event", "ticket_updated")
        return WebhookEvent(
            event_type=event_type,
            external_id=ext_id,
            raw=payload,
        )