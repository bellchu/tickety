import os
import re
import time
import asyncio
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime, timezone
from typing import Any, List, Optional

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

FRESHSERVICE_STATUS_MAP = {
    2: "Open",
    3: "Pending",
    4: "Resolved",
    5: "Closed",
    6: "Escalated",
}

DEFAULT_FRESHSERVICE_OAUTH_SCOPES = (
    "freshservice.tickets.view freshservice.agents.manage "
    "freshservice.requesters.view"
)
ALLOWED_FRESHSERVICE_OAUTH_SCOPES = frozenset(
    DEFAULT_FRESHSERVICE_OAUTH_SCOPES.split()
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

    def __init__(self, config: Optional[dict[str, Any]] = None):
        config = config or {}

        def configured(name: str, default: str = "") -> str:
            value = config.get(name)
            return str(value) if value is not None else os.getenv(name, default)

        self.domain = self._normalize_domain(
            configured("FRESHSERVICE_DOMAIN", "yourdomain.freshservice.com")
        )
        self.org_domain = self._normalize_domain(
            configured("FRESHWORKS_ORG_DOMAIN", self.domain)
        )
        self.api_key = configured("FRESHSERVICE_API_KEY", "dummy-key")
        self.base_url = f"https://{self.domain}"
        self.org_base_url = f"https://{self.org_domain}"
        self.webhook_secret = configured("WEBHOOK_SECRET")
        self.workspace_id = configured("FRESHSERVICE_WORKSPACE_ID").strip()
        self.ticket_includes = configured(
            "FRESHSERVICE_TICKET_INCLUDES", DEFAULT_TICKET_LIST_INCLUDES
        )
        self.agent_state = configured("FRESHSERVICE_AGENT_STATE").strip().lower()

        # OAuth 2.0
        self.oauth_client_id = configured("FRESHSERVICE_OAUTH_CLIENT_ID")
        self.oauth_client_secret = configured("FRESHSERVICE_OAUTH_CLIENT_SECRET")
        self.oauth_redirect_uri = configured("FRESHSERVICE_OAUTH_REDIRECT_URI")
        self.oauth_scopes = self._validate_oauth_scopes(
            configured(
                "FRESHSERVICE_OAUTH_SCOPES", DEFAULT_FRESHSERVICE_OAUTH_SCOPES
            )
        )
        self.oauth_access_token = configured("FRESHSERVICE_OAUTH_ACCESS_TOKEN")
        self.oauth_refresh_token = configured("FRESHSERVICE_OAUTH_REFRESH_TOKEN")

    @staticmethod
    def _normalize_domain(value: str) -> str:
        value = (value or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
        return parsed.netloc or parsed.path

    @staticmethod
    def _validate_oauth_scopes(value: str) -> str:
        scopes = [scope for scope in str(value or "").split() if scope]
        unknown = sorted(set(scopes) - ALLOWED_FRESHSERVICE_OAUTH_SCOPES)
        if unknown:
            raise ValueError(
                "Freshservice OAuth scopes exceed Tickety's read-only allowlist: "
                + ", ".join(unknown)
            )
        if "freshservice.tickets.view" not in scopes:
            raise ValueError("Freshservice OAuth requires freshservice.tickets.view")
        return " ".join(dict.fromkeys(scopes))

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
            "scope": self.oauth_scopes,
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
            db.commit()
            for key, value in updates.items():
                os.environ[key] = value
        except Exception as exc:
            db.rollback()
            print(
                "[External] failed to persist refreshed OAuth token "
                f"kind={type(exc).__name__}"
            )
            raise RuntimeError("OAuth token persistence failed") from exc
        finally:
            db.close()

    async def _refresh_oauth_access_token(self) -> bool:
        if not (self.oauth_configured and self.oauth_refresh_token):
            return False
        try:
            token_data = await self.oauth_refresh()
        except Exception as exc:
            print(f"[External] OAuth refresh failed kind={type(exc).__name__}")
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

    def _configured_ticket_includes(self) -> str:
        raw = self.ticket_includes
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

    def _parse_ticket_batch(self, raw_tickets: list) -> List[ExternalTicket]:
        """Validate provider records independently so one poison record cannot
        discard otherwise valid tickets from the same page."""
        parsed: List[ExternalTicket] = []
        for raw in raw_tickets:
            try:
                parsed.append(self._parse_ticket(raw))
            except Exception as exc:
                print(
                    "[External] Freshservice ticket parse skipped "
                    f"kind={type(exc).__name__}"
                )
        return parsed

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
        workspace_id = self.workspace_id
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
                if not isinstance(data, dict):
                    raise RuntimeError("Freshservice ticket response must be an object")
                tickets = data.get("tickets", [])
                if not isinstance(tickets, list):
                    raise RuntimeError("Freshservice tickets must be a list")
                out.extend(self._parse_ticket_batch(tickets))
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
        agent_state = self.agent_state
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

    async def fetch_requesters(self, max_pages: Optional[int] = None) -> List[dict]:
        """Fetch requester/contact profiles through the documented read API."""
        self._ensure_provider_configured()
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[dict] = []
        page = 1
        url = f"{self.base_url}/api/v2/requesters"
        params: dict = {"per_page": 100}
        async with httpx.AsyncClient(timeout=30) as client:
            while page <= cap:
                params["page"] = page
                resp = await self._rate_limited_get(client, url, params)
                if resp.status_code == 429:
                    raise RuntimeError(
                        f"Freshservice still rate-limited on requester page {page}"
                    )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict) or not isinstance(data.get("requesters", []), list):
                    raise RuntimeError("Freshservice requester response is invalid")
                requesters = data.get("requesters", [])
                out.extend(requesters)
                if not self._parse_link_next(resp.headers.get("link"), self.base_url):
                    break
                if len(requesters) < 100:
                    break
                page += 1
        return out

    async def fetch_external_users(self, max_pages: Optional[int] = None) -> List[dict]:
        agents = await self.fetch_agents(max_pages=max_pages)
        requesters = await self.fetch_requesters(max_pages=max_pages)
        return [
            *({**agent, "user_type": "agent"} for agent in agents),
            *({**requester, "user_type": "requester"} for requester in requesters),
        ]

    async def fetch_ticket_raw(self, external_id: str) -> dict:
        """Fetch one authoritative Freshservice ticket snapshot."""
        self._ensure_provider_configured()
        if not str(external_id).isdigit():
            raise ValueError("Freshservice ticket ID must be numeric")
        url = f"{self.base_url}/api/v2/tickets/{external_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await self._rate_limited_get(client, url, {})
            resp.raise_for_status()
            data = resp.json()
        ticket = data.get("ticket") if isinstance(data, dict) else None
        if not isinstance(ticket, dict):
            raise RuntimeError("Freshservice ticket response is invalid")
        return ticket

    def capability_manifest(self) -> dict[str, dict[str, Any]]:
        return {
            "integration.mode": {"status": "supported", "mode": "read_only"},
            "ticket.read": {"status": "supported", "scope": "freshservice.tickets.view"},
            "agent.read": {"status": "supported", "scope": "freshservice.agents.manage"},
            "requester.read": {"status": "supported", "scope": "freshservice.requesters.view"},
            "ticket.create": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.update": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.reply": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.note": {"status": "unsupported", "reason": "read_only_sidecar"},
            "ticket.attachment": {"status": "unsupported", "reason": "read_only_sidecar"},
            "service_request.create": {"status": "unsupported", "reason": "read_only_sidecar"},
            "webhook.ingest": {"status": "supported"},
            "freshworks.full_page_app": {"status": "unknown"},
            "freshworks.ticket_sidebar": {"status": "unknown"},
        }

    async def probe_capabilities(self) -> dict[str, dict[str, Any]]:
        """Probe only bounded API reads; app-placement checks remain client-side."""
        manifest = {key: dict(value) for key, value in self.capability_manifest().items()}
        try:
            self._ensure_provider_configured()
        except Exception as exc:
            detail = type(exc).__name__
            for key in ("ticket.read", "agent.read", "requester.read"):
                manifest[key] = {**manifest[key], "status": "degraded", "detail": detail}
            return manifest

        async with httpx.AsyncClient(timeout=15) as client:
            probes = {
                "ticket.read": (f"{self.base_url}/api/v2/tickets", {"per_page": 1}),
                "agent.read": (f"{self.base_url}/api/v2/agents", {"per_page": 1, "active": "true"}),
                "requester.read": (f"{self.base_url}/api/v2/requesters", {"per_page": 1}),
            }
            for capability, (url, params) in probes.items():
                try:
                    response = await self._rate_limited_get(client, url, params)
                    if response.status_code < 400:
                        status = "supported"
                    elif response.status_code in {401, 403}:
                        status = "restricted"
                    elif response.status_code == 429:
                        status = "degraded"
                    else:
                        status = "unsupported"
                    manifest[capability] = {
                        **manifest[capability],
                        "status": status,
                        "http_status": response.status_code,
                    }
                except Exception as exc:
                    manifest[capability] = {
                        **manifest[capability],
                        "status": "degraded",
                        "detail": type(exc).__name__,
                    }
        return manifest

    def parse_webhook(
        self,
        payload: dict,
        headers: dict,
        raw_body: bytes | None = None,
    ) -> Optional[WebhookEvent]:
        body = raw_body if raw_body is not None else str(payload).encode()
        if not self.verify_webhook_signature(headers, body):
            return None
        return self.parse_verified_webhook(payload)

    def verify_webhook_signature(self, headers: dict, raw_body: bytes) -> bool:
        """Authenticate the raw delivery before any JSON parser sees it."""
        signature = headers.get("x-freshservice-webhook-signature", "")
        timestamp = headers.get("x-freshservice-webhook-timestamp", "")
        if not self.webhook_secret or self.webhook_secret in {
            "your-webhook-secret",
            "change-me",
        }:
            print("[External] webhook secret is not configured")
            return False
        if not signature:
            print("[External] webhook signature missing")
            return False
        if not timestamp.isascii() or not timestamp.isdigit():
            print("[External] webhook timestamp invalid")
            return False
        try:
            timestamp_seconds = int(timestamp)
            max_age = max(
                30,
                min(int(os.getenv("WEBHOOK_MAX_AGE_SECONDS", "300")), 3600),
            )
        except (TypeError, ValueError):
            print("[External] webhook timestamp invalid")
            return False
        if timestamp_seconds <= 0 or abs(int(time.time()) - timestamp_seconds) > max_age:
            print("[External] webhook timestamp expired")
            return False
        signed_body = timestamp.encode("ascii") + b"." + raw_body
        expected = base64.b64encode(
            hmac.new(self.webhook_secret.encode(), signed_body, hashlib.sha256).digest()
        ).decode()
        if not hmac.compare_digest(signature, expected):
            print("[External] webhook signature mismatch")
            return False
        return True

    @staticmethod
    def parse_verified_webhook(payload: dict) -> Optional[WebhookEvent]:
        if not isinstance(payload, dict):
            return None
        ticket_data = payload.get("ticket", payload.get("data", {}))
        if not isinstance(ticket_data, dict):
            return None
        ext_id = str(ticket_data.get("id", ""))
        if not ext_id:
            return None

        event_type = payload.get("event", "ticket_updated")
        return WebhookEvent(
            event_type=event_type,
            external_id=ext_id,
            raw=payload,
        )
