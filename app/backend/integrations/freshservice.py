import os
import re
import time
import asyncio
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime
from typing import List, Optional

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
        self.domain = self._normalize_domain(os.getenv("FRESHSERVICE_DOMAIN") or "yourdomain.freshservice.com")
        self.org_domain = self._normalize_domain(os.getenv("FRESHWORKS_ORG_DOMAIN") or self.domain)
        self.api_key = os.getenv("FRESHSERVICE_API_KEY", "dummy-key")
        self.base_url = f"https://{self.domain}"
        self.org_base_url = f"https://{self.org_domain}"
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "")

        # OAuth 2.0
        self.oauth_client_id = os.getenv("FRESHSERVICE_OAUTH_CLIENT_ID", "")
        self.oauth_client_secret = os.getenv("FRESHSERVICE_OAUTH_CLIENT_SECRET", "")
        self.oauth_redirect_uri = os.getenv("FRESHSERVICE_OAUTH_REDIRECT_URI", "")
        self.oauth_access_token = os.getenv("FRESHSERVICE_OAUTH_ACCESS_TOKEN", "")
        self.oauth_refresh_token = os.getenv("FRESHSERVICE_OAUTH_REFRESH_TOKEN", "")

    @staticmethod
    def _normalize_domain(value: str) -> str:
        value = (value or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
        return parsed.netloc or parsed.path

    def _auth(self):
        """Return Basic‑auth tuple (apikey, X) unless OAuth is configured, in
        which case returns (None, None) — _headers() will attach the Bearer token."""
        if self.oauth_access_token:
            return None
        return (self.api_key, "X")

    def _headers(self) -> dict:
        h: dict = {"Content-Type": "application/json"}
        if self.oauth_access_token:
            h["Authorization"] = f"Bearer {self.oauth_access_token}"
        return h

    @property
    def oauth_configured(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret and self.oauth_redirect_uri)

    def oauth_authorization_url(self, state: str) -> str:
        """Build the OAuth 2.0 authorisation URL."""
        params = {
            "client_id": self.oauth_client_id,
            "redirect_uri": self.oauth_redirect_uri,
            "response_type": "code",
            "scope": os.getenv("FRESHSERVICE_OAUTH_SCOPES", "freshservice.tickets.view freshservice.tickets.edit"),
            "state": state,
        }
        return f"{self.org_base_url}/org/oauth/v2/authorize?{urllib.parse.urlencode(params)}"

    async def oauth_exchange_code(self, code: str) -> dict:
        """Exchange an OAuth authorisation code for access & refresh tokens."""
        url = f"{self.org_base_url}/org/oauth/v2/token"
        payload = {
            "grant_type": "authorization_code",
            "redirect_uri": self.oauth_redirect_uri,
            "code": code,
        }
        auth = base64.b64encode(
            f"{self.oauth_client_id}:{self.oauth_client_secret}".encode("utf-8")
        ).decode("ascii")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                data=payload,
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def oauth_refresh(self) -> dict:
        """Refresh an expired OAuth access token."""
        url = f"{self.org_base_url}/org/oauth/v2/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.oauth_refresh_token,
        }
        auth = base64.b64encode(
            f"{self.oauth_client_id}:{self.oauth_client_secret}".encode("utf-8")
        ).decode("ascii")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                data=payload,
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            )
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

    @staticmethod
    def _parse_datetime(value) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    def _parse_ticket(self, raw: dict) -> ExternalTicket:
        stats = raw.get("stats") or {}
        requester = raw.get("requester") or {}
        return ExternalTicket(
            external_id=str(raw.get("id", "")),
            subject=raw.get("subject", "(no subject)"),
            description=raw.get("description_text", raw.get("description", "")) or "",
            reporter=str(requester.get("email") or raw.get("email") or raw.get("requester_id", "")),
            priority=self.map_priority(raw.get("priority", 3)),
            status=self.map_status(raw.get("status", 2)),
            assignee_id=str(raw.get("responder_id")) if raw.get("responder_id") else None,
            updated_at=self._parse_datetime(raw.get("updated_at")),
            created_at=self._parse_datetime(raw.get("created_at")),
            resolved_at=self._parse_datetime(
                stats.get("resolved_at") or stats.get("closed_at") or raw.get("resolved_at") or raw.get("closed_at")
            ),
            due_by=self._parse_datetime(raw.get("due_by")),
            fr_due_by=self._parse_datetime(raw.get("fr_due_by")),
            ticket_type=str(raw.get("type") or raw.get("ticket_type") or ""),
            requester_email=requester.get("email") or raw.get("email"),
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
            await asyncio.sleep(self._MIN_INTERVAL_S - elapsed)

        resp = await client.get(url, auth=self._auth(), headers=self._headers(), params=params)
        self._last_get_ts = time.monotonic()

        # Honor remaining-budget header: if we're close to the limit,
        # wait out the rest of the window so the next call doesn't 429.
        remaining = resp.headers.get("X-Ratelimit-Remaining")
        if remaining is not None:
            try:
                if int(remaining) <= 2:
                    await asyncio.sleep(2.0)
            except ValueError:
                pass

        # 429 -> respect Retry-After (seconds) then retry once.
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5") or "5")
            print(f"[External] rate limited; sleeping {retry_after}s")
            await asyncio.sleep(retry_after + 0.5)
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
        complete paginated set of tickets updated since `since`."""
        return await self.fetch_tickets_since(since)

    async def fetch_updated_tickets(self, since: datetime) -> List[ExternalTicket]:
        return await self.fetch_new_tickets(since=since)

    async def fetch_tickets_since(self, since: Optional[datetime], max_pages: Optional[int] = None) -> List[ExternalTicket]:
        """Fetch ALL tickets updated since `since`, walking every page while
        respecting provider rate limits. Used by the manual "fetch by days"
        feature. Stops when a page is empty/short or when the Link header has no
        rel="next". `max_pages` defaults to FRESHSERVICE_MAX_PAGES as a safety cap."""
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[ExternalTicket] = []
        page = 1
        url = f"{self.base_url}/api/v2/tickets"
        params = {"per_page": 100, "include": "stats,requester"}
        if since:
            params["updated_since"] = since.isoformat()
        async with httpx.AsyncClient(timeout=30) as client:
            while page <= cap:
                params["page"] = page
                resp = await self._rate_limited_get(client, url, params)
                if resp.status_code == 429:
                    # _rate_limited_get already retried once; if still 429, fail the sync.
                    raise RuntimeError(f"Freshservice still rate-limited on page {page}")
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
        out.sort(key=lambda t: (t.updated_at or datetime.min, t.external_id))
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
        async with httpx.AsyncClient(timeout=30) as client:
            while page <= cap:
                params["page"] = page
                resp = await self._rate_limited_get(client, url, params)
                if resp.status_code == 429:
                    raise RuntimeError(f"Freshservice still rate-limited on agent page {page}")
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

    def parse_webhook(
        self,
        payload: dict,
        headers: dict,
        raw_body: bytes | None = None,
    ) -> Optional[WebhookEvent]:
        signature = headers.get("x-freshservice-webhook-signature", "")
        if not self.webhook_secret and os.getenv("APP_MODE", "demo").lower() == "production":
            print("[External] webhook secret missing in production")
            return None
        if self.webhook_secret and not signature:
            print("[External] webhook signature missing")
            return None
        if self.webhook_secret and signature:
            body = raw_body if raw_body is not None else str(payload).encode()
            expected = base64.b64encode(
                hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).digest()
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
