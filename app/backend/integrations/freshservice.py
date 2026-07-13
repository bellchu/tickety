import os
import re
import time
import asyncio
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from ..database import SessionLocal, SettingsRecord
from ..schema import ExternalTicket, WebhookEvent
from .base import BaseITSMAdapter

FRESHSERVICE_PRIORITY_MAP = {
    1: "P4",  # Low
    2: "P3",  # Medium
    3: "P2",  # High
    4: "P1",  # Urgent
}

TICKETY_PRIORITY_TO_FRESHSERVICE = {
    "P4": 1,
    "LOW": 1,
    "P3": 2,
    "MEDIUM": 2,
    "P2": 3,
    "HIGH": 3,
    "P1": 4,
    "URGENT": 4,
}

FRESHSERVICE_STATUS_MAP = {
    2: "Open",
    3: "Pending",
    4: "Resolved",
    5: "Closed",
    6: "Escalated",
}

TICKETY_STATUS_TO_FRESHSERVICE = {
    "NEW": 2,
    "OPEN": 2,
    "AWAITING REVIEW": 3,
    "PENDING": 3,
    "RESOLVED": 4,
    "CLOSED": 5,
    "ESCALATED": 6,
}

DEFAULT_FRESHSERVICE_OAUTH_SCOPES = (
    "freshservice.tickets.view freshservice.tickets.edit freshservice.agents.manage"
)
DEFAULT_TICKET_LIST_INCLUDES = "stats,requester"
SUPPORTED_TICKET_LIST_INCLUDES = {
    "stats",
    "requester",
    "requested_for",
    "onboarding_context",
    "offboarding_context",
}
PLACEHOLDER_FRESHSERVICE_DOMAINS = {
    "",
    "demo.freshservice.com",
    "yourdomain.freshservice.com",
    "yourdomain.example.com",
    "acme.freshservice.com",
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
            "scope": os.getenv("FRESHSERVICE_OAUTH_SCOPES", DEFAULT_FRESHSERVICE_OAUTH_SCOPES),
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

    def _persist_oauth_tokens(self, access_token: str, refresh_token: Optional[str]) -> None:
        updates = {"FRESHSERVICE_OAUTH_ACCESS_TOKEN": access_token}
        if refresh_token:
            updates["FRESHSERVICE_OAUTH_REFRESH_TOKEN"] = refresh_token
        db = SessionLocal()
        try:
            for key, value in updates.items():
                row = db.query(SettingsRecord).filter(SettingsRecord.key == key).first()
                if row:
                    row.value = value
                else:
                    db.add(SettingsRecord(key=key, value=value))
                os.environ[key] = value
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"[External] failed to persist refreshed OAuth token: {exc}")
        finally:
            db.close()

    async def _refresh_oauth_access_token(self) -> bool:
        if not (self.oauth_configured and self.oauth_refresh_token):
            return False
        try:
            token_data = await self.oauth_refresh()
        except Exception as exc:
            print(f"[External] OAuth refresh failed: {exc}")
            return False
        access_token = token_data.get("access_token")
        if not access_token:
            return False
        refresh_token = token_data.get("refresh_token") or self.oauth_refresh_token
        self.oauth_access_token = access_token
        self.oauth_refresh_token = refresh_token
        self._persist_oauth_tokens(access_token, refresh_token)
        return True

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

    def to_freshservice_priority(self, tickety_priority) -> int:
        key = str(tickety_priority or "P3").strip().upper()
        return TICKETY_PRIORITY_TO_FRESHSERVICE.get(key, 2)

    def to_freshservice_status(self, tickety_status) -> int:
        key = str(tickety_status or "Open").strip().upper()
        return TICKETY_STATUS_TO_FRESHSERVICE.get(key, 2)

    def build_ticket_url(self, external_id: str) -> str:
        return f"{self.base_url}/support/tickets/{external_id}"

    def _ensure_provider_configured(self) -> None:
        if self.domain in PLACEHOLDER_FRESHSERVICE_DOMAINS:
            raise RuntimeError(
                "Freshservice is selected, but the saved domain is still a placeholder. "
                "Set the Freshservice Domain in Ticketing Mode and save settings before syncing."
            )
        if not self.oauth_access_token and self.api_key in {"", "dummy-key", "your-key-here"}:
            raise RuntimeError(
                "Freshservice is selected, but no API key or OAuth token is configured. "
                "Add an authentication method in Ticketing Mode before syncing."
            )

    @staticmethod
    def _parse_datetime(value) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=0).isoformat() + "Z"

    @staticmethod
    def _configured_ticket_includes() -> str:
        raw = os.getenv("FRESHSERVICE_TICKET_INCLUDES", DEFAULT_TICKET_LIST_INCLUDES)
        includes: list[str] = []
        for item in raw.split(","):
            include = item.strip()
            if include in SUPPORTED_TICKET_LIST_INCLUDES and include not in includes:
                includes.append(include)
        return ",".join(includes)

    def _parse_ticket(self, raw: dict) -> ExternalTicket:
        stats = raw.get("stats") or {}
        requester = raw.get("requester") or {}
        requested_for = raw.get("requested_for") or {}
        return ExternalTicket(
            external_id=str(raw.get("id", "")),
            subject=raw.get("subject", "(no subject)"),
            description=raw.get("description_text", raw.get("description", "")) or "",
            reporter=str(
                requester.get("email")
                or requested_for.get("email")
                or raw.get("email")
                or raw.get("requester_id")
                or raw.get("requested_for_id")
                or ""
            ),
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
            external_workspace_id=str(raw.get("workspace_id")) if raw.get("workspace_id") is not None else None,
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
        if resp.status_code == 401 and await self._refresh_oauth_access_token():
            self._last_get_ts = time.monotonic()
            resp = await client.get(url, auth=self._auth(), headers=self._headers(), params=params)
        return resp

    async def _rate_limited_post(self, client: httpx.AsyncClient, url: str, payload: dict) -> httpx.Response:
        """POST with rate-limit pacing + 429 retry. Returns the Response."""
        elapsed = time.monotonic() - getattr(self, "_last_post_ts", 0.0)
        if elapsed < self._MIN_INTERVAL_S:
            await asyncio.sleep(self._MIN_INTERVAL_S - elapsed)

        resp = await client.post(url, auth=self._auth(), headers=self._headers(), json=payload)
        self._last_post_ts = time.monotonic()

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5") or "5")
            print(f"[External] rate limited; sleeping {retry_after}s")
            await asyncio.sleep(retry_after + 0.5)
            self._last_post_ts = time.monotonic()
            resp = await client.post(url, auth=self._auth(), headers=self._headers(), json=payload)
        if resp.status_code == 401 and await self._refresh_oauth_access_token():
            self._last_post_ts = time.monotonic()
            resp = await client.post(url, auth=self._auth(), headers=self._headers(), json=payload)
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
        self._ensure_provider_configured()
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[ExternalTicket] = []
        page = 1
        url = f"{self.base_url}/api/v2/tickets"
        params = {"per_page": 100}
        includes = self._configured_ticket_includes()
        if includes:
            params["include"] = includes
        workspace_id = os.getenv("FRESHSERVICE_WORKSPACE_ID", "").strip()
        if workspace_id:
            params["workspace_id"] = workspace_id
        if since:
            params["updated_since"] = self._format_datetime(since)
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
        self._ensure_provider_configured()
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[dict] = []
        page = 1
        url = f"{self.base_url}/api/v2/agents"
        # Provider API detail: filter to active agents only.
        params: dict = {"per_page": 100, "active": "true"}
        agent_state = os.getenv("FRESHSERVICE_AGENT_STATE", "").strip().lower()
        if agent_state in {"fulltime", "occasional"}:
            params["state"] = agent_state
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

    async def create_ticket(self, payload: dict) -> dict:
        """Create a ticket in Freshservice and return the raw provider ticket."""
        self._ensure_provider_configured()
        url = f"{self.base_url}/api/v2/tickets"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await self._rate_limited_post(client, url, payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("ticket", data)

    def parse_webhook(
        self,
        payload: dict,
        headers: dict,
        raw_body: bytes | None = None,
    ) -> Optional[WebhookEvent]:
        signature = headers.get("x-freshservice-webhook-signature", "")
        if not self.webhook_secret or self.webhook_secret in {
            "your-webhook-secret",
            "change-me",
        }:
            print("[External] webhook secret is not configured")
            return None
        if not signature:
            print("[External] webhook signature missing")
            return None
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
