import os
import re
import time
import asyncio
import hmac
import hashlib
import base64
import urllib.parse
import ipaddress
import socket
from email.utils import parseaddr
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx

from ..database import SessionLocal, SettingsRecord
from ..schema import ExternalAttachment, ExternalConversation, ExternalTicket, WebhookEvent
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
    "freshservice.tickets.view freshservice.tickets.conversations.view "
    "freshservice.agents.manage "
    "freshservice.requesters.view"
)
ALLOWED_FRESHSERVICE_OAUTH_SCOPES = frozenset(
    DEFAULT_FRESHSERVICE_OAUTH_SCOPES.split()
)
# Requester identity is required operational ticket data. The provider's
# account-wide directory may be unavailable to otherwise valid ticket-reader
# credentials, so every bounded ticket page carries its requester projection.
DEFAULT_TICKET_LIST_INCLUDES = "requester"
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


class FreshserviceRateLimited(RuntimeError):
    """A non-fatal provider pause carrying the authoritative retry delay."""

    def __init__(self, retry_after: float):
        self.retry_after = max(1.0, retry_after)
        super().__init__("Freshservice rate limit window is exhausted")


@dataclass(frozen=True)
class FreshserviceTicketPage:
    tickets: List[ExternalTicket]
    page: int
    workspace_index: int
    workspace_count: int
    has_next_page: bool


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
        configured_workspace_ids = configured("FRESHSERVICE_WORKSPACE_IDS")
        self.workspace_ids = tuple(dict.fromkeys(
            value.strip()
            for value in configured_workspace_ids.split(",")
            if value.strip()
        )) or ((self.workspace_id,) if self.workspace_id else tuple())
        self.ticket_includes = configured(
            "FRESHSERVICE_TICKET_INCLUDES", DEFAULT_TICKET_LIST_INCLUDES
        )
        self.agent_state = configured("FRESHSERVICE_AGENT_STATE").strip().lower()
        try:
            self.min_interval_s = max(
                0.25, float(configured("FRESHSERVICE_MIN_INTERVAL_SECONDS", "1.6"))
            )
        except (TypeError, ValueError):
            self.min_interval_s = 1.6
        try:
            self.rate_limit_reserve = max(
                2, int(configured("FRESHSERVICE_RATE_LIMIT_RESERVE", "10"))
            )
        except (TypeError, ValueError):
            self.rate_limit_reserve = 10
        self._rate_limit_total: Optional[int] = None
        self._rate_limit_remaining: Optional[int] = None
        self._rate_limit_used: Optional[int] = None
        self._last_retry_after: Optional[float] = None

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
                "Freshservice OAuth scopes exceed Tickety OPS Tower's read-only allowlist: "
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
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
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
        requester_name = (
            requester.get("name")
            or " ".join(
                str(requester.get(key) or "").strip()
                for key in ("first_name", "last_name")
            ).strip()
            or requested_for.get("name")
            or " ".join(
                str(requested_for.get(key) or "").strip()
                for key in ("first_name", "last_name")
            ).strip()
        )
        requester_email = (
            requester.get("email")
            or requested_for.get("email")
            or raw.get("email")
        )
        return ExternalTicket(
            external_id=str(raw.get("id", "")),
            # Freshservice permits an explicitly empty subject on legacy
            # records.  Normalize that provider value so one historical
            # record cannot poison an otherwise valid inventory page.
            subject=raw.get("subject") or "(no subject)",
            description=raw.get("description_text", raw.get("description", "")) or "",
            description_html=(
                str(raw.get("description"))
                if raw.get("description") is not None else None
            ),
            reporter=str(
                requester_email
                or raw.get("requester_id")
                or raw.get("requested_for_id")
                or ""
            ),
            priority=self.map_priority(raw.get("priority", 3)),
            external_priority_code=(
                str(raw.get("priority")) if raw.get("priority") is not None else None
            ),
            status=self.map_status(raw.get("status", 2)),
            external_status_code=(
                str(raw.get("status")) if raw.get("status") is not None else None
            ),
            assignee_id=str(raw.get("responder_id")) if raw.get("responder_id") else None,
            external_group_id=str(raw.get("group_id")) if raw.get("group_id") else None,
            external_category=str(raw.get("category")) if raw.get("category") else None,
            external_subcategory=(
                str(raw.get("sub_category")) if raw.get("sub_category") else None
            ),
            external_item_category=(
                str(raw.get("item_category")) if raw.get("item_category") else None
            ),
            updated_at=self._parse_datetime(raw.get("updated_at")),
            created_at=self._parse_datetime(raw.get("created_at")),
            resolved_at=self._parse_datetime(
                stats.get("resolved_at") or stats.get("closed_at") or raw.get("resolved_at") or raw.get("closed_at")
            ),
            due_by=self._parse_datetime(raw.get("due_by")),
            fr_due_by=self._parse_datetime(raw.get("fr_due_by")),
            ticket_type=str(raw.get("type") or raw.get("ticket_type") or ""),
            requester_id=(
                str(raw.get("requester_id") or raw.get("requested_for_id"))
                if raw.get("requester_id") or raw.get("requested_for_id") else None
            ),
            requester_name=str(requester_name) if requester_name else None,
            requester_email=str(requester_email) if requester_email else None,
            requester_title=(
                str(
                    requester.get("job_title")
                    or requested_for.get("job_title")
                )
                if requester.get("job_title") or requested_for.get("job_title")
                else None
            ),
            external_workspace_id=str(raw.get("workspace_id")) if raw.get("workspace_id") is not None else None,
            url=self.build_ticket_url(str(raw.get("id", ""))),
            attachments=self._parse_attachments(raw.get("attachments", [])),
        )

    @staticmethod
    def _parse_attachment(raw: dict) -> ExternalAttachment:
        if not isinstance(raw, dict):
            raise ValueError("Freshservice attachment must be an object")
        external_id = raw.get("id")
        download_url = raw.get("attachment_url") or raw.get("Attachment_url")
        name = raw.get("name") or raw.get("file_name")
        if external_id is None or not download_url or not name:
            raise ValueError("Freshservice attachment metadata is incomplete")
        size = raw.get("size")
        try:
            parsed_size = int(size) if size is not None else None
        except (TypeError, ValueError):
            parsed_size = None
        return ExternalAttachment(
            external_id=str(external_id),
            name=str(name),
            content_type=(
                str(raw.get("content_type"))
                if raw.get("content_type") is not None else None
            ),
            size=parsed_size,
            download_url=str(download_url),
        )

    @classmethod
    def _parse_attachments(cls, raw_attachments: Any) -> List[ExternalAttachment]:
        if raw_attachments is None:
            return []
        if not isinstance(raw_attachments, list):
            raise ValueError("Freshservice attachments must be a list")
        return [cls._parse_attachment(raw) for raw in raw_attachments]

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
    _MAX_PAGES = int(os.getenv("FRESHSERVICE_MAX_PAGES", "500"))

    @staticmethod
    def _header_int(response: httpx.Response, name: str) -> Optional[int]:
        value = response.headers.get(name)
        if value is None:
            return None
        try:
            # Freshservice currently serializes these numeric headers as both
            # integers ("70") and decimal strings ("70.0") across accounts.
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _capture_rate_limit(self, response: httpx.Response) -> None:
        self._rate_limit_total = self._header_int(response, "X-RateLimit-Total")
        self._rate_limit_remaining = self._header_int(
            response, "X-RateLimit-Remaining"
        )
        self._rate_limit_used = self._header_int(
            response, "X-RateLimit-Used-CurrentRequest"
        )
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            self._last_retry_after = None
        else:
            try:
                self._last_retry_after = max(1.0, float(retry_after))
            except (TypeError, ValueError):
                self._last_retry_after = 60.0

    def rate_limit_snapshot(self) -> dict[str, Optional[int]]:
        return {
            "total": self._rate_limit_total,
            "remaining": self._rate_limit_remaining,
            "used": self._rate_limit_used,
        }

    def should_pause_requests(self) -> bool:
        return (
            self._rate_limit_remaining is not None
            and self._rate_limit_remaining <= self.rate_limit_reserve
        )

    async def _rate_limited_get(self, client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
        """GET with pacing and a non-blocking, durable 429 handoff."""
        # Pace consecutive provider requests even when they use different
        # endpoint-specific sub-limits.
        elapsed = time.monotonic() - getattr(self, "_last_get_ts", 0.0)
        if elapsed < self.min_interval_s:
            await asyncio.sleep(self.min_interval_s - elapsed)

        resp = await client.get(url, auth=self._auth(), headers=self._headers(), params=params)
        self._last_get_ts = time.monotonic()
        if resp.status_code == 401 and await self._refresh_oauth_access_token():
            elapsed = time.monotonic() - getattr(self, "_last_get_ts", 0.0)
            if elapsed < self.min_interval_s:
                await asyncio.sleep(self.min_interval_s - elapsed)
            self._last_get_ts = time.monotonic()
            resp = await client.get(url, auth=self._auth(), headers=self._headers(), params=params)
        self._capture_rate_limit(resp)
        # Do not occupy the worker for a provider window that can be many
        # minutes long. The orchestrator persists Retry-After and makes no more
        # requests until it expires.
        if resp.status_code == 429:
            raise FreshserviceRateLimited(self._last_retry_after or 60.0)
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

    async def fetch_ticket_page(
        self,
        *,
        since: Optional[datetime],
        page: int,
        workspace_index: int = 0,
        order_type: str = "asc",
        include_resources: bool = False,
    ) -> FreshserviceTicketPage:
        """Fetch one lightweight, resumable ticket page.

        The sync orchestrator persists this page before requesting another.
        Ascending order keeps historical page boundaries stable as new tickets
        arrive at the end of the provider inventory.
        """
        self._ensure_provider_configured()
        page = max(1, int(page))
        if order_type not in {"asc", "desc"}:
            raise ValueError("Freshservice ticket order must be asc or desc")
        workspace_scopes: tuple[Optional[str], ...] = (
            tuple(self.workspace_ids) if self.workspace_ids else (None,)
        )
        if workspace_index < 0 or workspace_index >= len(workspace_scopes):
            raise ValueError("Freshservice workspace cursor is out of range")
        params: dict[str, Any] = {
            "per_page": 100,
            "page": page,
            "order_type": order_type,
        }
        if since:
            params["updated_since"] = self._format_datetime(since)
        workspace_id = workspace_scopes[workspace_index]
        if workspace_id is not None:
            params["workspace_id"] = workspace_id
        if include_resources:
            includes = self._configured_ticket_includes()
            if includes:
                params["include"] = includes

        url = f"{self.base_url}/api/v2/tickets"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await self._rate_limited_get(client, url, params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Freshservice ticket response must be an object")
        raw_tickets = data.get("tickets", [])
        if not isinstance(raw_tickets, list):
            raise RuntimeError("Freshservice tickets must be a list")
        tickets = self._parse_ticket_batch(raw_tickets)
        if len(tickets) != len(raw_tickets):
            raise RuntimeError("Freshservice ticket page contained malformed records")
        ids = [ticket.external_id for ticket in tickets]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Freshservice ticket page returned duplicate IDs")
        return FreshserviceTicketPage(
            tickets=tickets,
            page=page,
            workspace_index=workspace_index,
            workspace_count=len(workspace_scopes),
            has_next_page=bool(
                self._parse_link_next(response.headers.get("link"), self.base_url)
            ),
        )

    async def fetch_tickets_since(self, since: Optional[datetime], max_pages: Optional[int] = None) -> List[ExternalTicket]:
        """Fetch ALL tickets updated since `since`, walking every page while
        respecting provider rate limits. Used by the manual "fetch by days"
        feature. Stops when a page is empty/short or when the Link header has no
        rel="next". `max_pages` defaults to FRESHSERVICE_MAX_PAGES as a safety cap."""
        self._ensure_provider_configured()
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[ExternalTicket] = []
        pages_used = 0
        url = f"{self.base_url}/api/v2/tickets"
        base_params = {"per_page": 100}
        includes = self._configured_ticket_includes()
        if includes:
            base_params["include"] = includes
        if since:
            base_params["updated_since"] = self._format_datetime(since)
        workspace_scopes: tuple[Optional[str], ...] = (
            tuple(self.workspace_ids) if self.workspace_ids else (None,)
        )
        async with httpx.AsyncClient(timeout=30) as client:
            for workspace_id in workspace_scopes:
                page = 1
                while True:
                    if pages_used >= cap:
                        raise RuntimeError(
                            "Freshservice ticket pagination exceeded the safety cap"
                        )
                    params = dict(base_params)
                    params["page"] = page
                    if workspace_id is not None:
                        params["workspace_id"] = workspace_id
                    pages_used += 1
                    resp = await self._rate_limited_get(client, url, params)
                    if resp.status_code == 429:
                        raise RuntimeError(
                            f"Freshservice still rate-limited on page {page}"
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    if not isinstance(data, dict):
                        raise RuntimeError(
                            "Freshservice ticket response must be an object"
                        )
                    tickets = data.get("tickets", [])
                    if not isinstance(tickets, list):
                        raise RuntimeError("Freshservice tickets must be a list")
                    parsed_tickets = self._parse_ticket_batch(tickets)
                    if len(parsed_tickets) != len(tickets):
                        raise RuntimeError(
                            "Freshservice ticket page contained malformed records"
                        )
                    out.extend(parsed_tickets)
                    next_link = self._parse_link_next(
                        resp.headers.get("link"), self.base_url
                    )
                    if not next_link:
                        break
                    page += 1
        out.sort(key=lambda t: (t.updated_at or datetime.min, t.external_id))
        ticket_ids = [ticket.external_id for ticket in out]
        if len(ticket_ids) != len(set(ticket_ids)):
            raise RuntimeError("Freshservice ticket pagination returned duplicate IDs")
        for ticket in out:
            ticket.conversations = await self.fetch_ticket_conversations(
                ticket.external_id
            )
            ticket.conversations_loaded = True
        return out

    def _parse_conversation(self, raw: dict) -> ExternalConversation:
        if raw.get("id") is None:
            raise ValueError("Freshservice conversation is missing its stable ID")
        body = raw.get("body_text", raw.get("body", "")) or ""
        author_name, author_email = parseaddr(str(raw.get("from_email") or ""))
        return ExternalConversation(
            external_id=str(raw.get("id", "")),
            body=str(body),
            body_html=(str(raw.get("body")) if raw.get("body") is not None else None),
            author_id=str(raw.get("user_id")) if raw.get("user_id") else None,
            author_name=author_name or None,
            author_email=author_email or None,
            is_private=bool(raw.get("private", False)),
            incoming=bool(raw.get("incoming", False)),
            source=int(raw["source"]) if raw.get("source") is not None else None,
            created_at=self._parse_datetime(raw.get("created_at")),
            updated_at=self._parse_datetime(raw.get("updated_at")),
            attachments=self._parse_attachments(raw.get("attachments", [])),
        )

    def _parse_conversation_batch(
        self, raw_conversations: list
    ) -> List[ExternalConversation]:
        if any(not isinstance(raw, dict) for raw in raw_conversations):
            raise ValueError("Freshservice conversation must be an object")
        return [self._parse_conversation(raw) for raw in raw_conversations]

    async def fetch_ticket_conversations(
        self, external_id: str, max_pages: Optional[int] = None
    ) -> List[ExternalConversation]:
        """Fetch the complete reply/note thread for one changed ticket."""
        self._ensure_provider_configured()
        if not str(external_id).isdigit():
            raise ValueError("Freshservice ticket ID must be numeric")
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        out: List[ExternalConversation] = []
        page = 1
        url = f"{self.base_url}/api/v2/tickets/{external_id}/conversations"
        params = {"per_page": 100}
        async with httpx.AsyncClient(timeout=30) as client:
            while page <= cap:
                params["page"] = page
                resp = await self._rate_limited_get(client, url, params)
                if resp.status_code == 429:
                    raise RuntimeError(
                        f"Freshservice still rate-limited on conversation page {page}"
                    )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise RuntimeError(
                        "Freshservice conversation response must be an object"
                    )
                conversations = data.get("conversations", [])
                if not isinstance(conversations, list):
                    raise RuntimeError("Freshservice conversations must be a list")
                out.extend(self._parse_conversation_batch(conversations))
                next_link = self._parse_link_next(
                    resp.headers.get("link"), self.base_url
                )
                if not next_link:
                    break
                if page >= cap:
                    raise RuntimeError(
                        "Freshservice conversation pagination exceeded the safety cap"
                    )
                page += 1
        out.sort(
            key=lambda item: (
                item.created_at or item.updated_at or datetime.min,
                item.external_id,
            )
        )
        conversation_ids = [item.external_id for item in out]
        if len(conversation_ids) != len(set(conversation_ids)):
            raise RuntimeError(
                "Freshservice conversation pagination returned duplicate IDs"
            )
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

    async def fetch_groups(self, max_pages: Optional[int] = None) -> List[dict]:
        """Fetch resolver groups in every configured Freshservice workspace."""
        self._ensure_provider_configured()
        cap = max_pages if max_pages is not None else self._MAX_PAGES
        workspace_scopes: tuple[Optional[str], ...] = (
            tuple(self.workspace_ids) if self.workspace_ids else (None,)
        )
        by_id: dict[str, dict] = {}
        async with httpx.AsyncClient(timeout=30) as client:
            for workspace_id in workspace_scopes:
                page = 1
                url = f"{self.base_url}/api/v2/groups"
                params: dict[str, Any] = {"per_page": 100}
                if workspace_id is not None:
                    params["workspace_id"] = workspace_id
                while page <= cap:
                    params["page"] = page
                    resp = await self._rate_limited_get(client, url, params)
                    if resp.status_code == 429:
                        raise RuntimeError(
                            f"Freshservice still rate-limited on group page {page}"
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    groups = data.get("groups", []) if isinstance(data, dict) else []
                    if not isinstance(groups, list):
                        raise RuntimeError("Freshservice group response is invalid")
                    for group in groups:
                        if not isinstance(group, dict) or group.get("id") is None:
                            continue
                        normalized = dict(group)
                        if normalized.get("workspace_id") is None and workspace_id is not None:
                            normalized["workspace_id"] = workspace_id
                        by_id[str(normalized["id"])] = normalized
                    if not self._parse_link_next(resp.headers.get("link"), self.base_url):
                        break
                    if len(groups) < 100:
                        break
                    page += 1
        return list(by_id.values())

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

    async def fetch_ticket_raw(
        self,
        external_id: str,
        *,
        include_attachments: bool = False,
        include_requester: bool = True,
    ) -> dict:
        """Fetch one authoritative Freshservice ticket snapshot."""
        self._ensure_provider_configured()
        if not str(external_id).isdigit():
            raise ValueError("Freshservice ticket ID must be numeric")
        url = f"{self.base_url}/api/v2/tickets/{external_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            includes = []
            if include_attachments:
                includes.append("ticket_attachments")
            if include_requester:
                includes.append("requester")
            params = {"include": ",".join(includes)} if includes else {}
            resp = await self._rate_limited_get(client, url, params)
            resp.raise_for_status()
            data = resp.json()
        ticket = data.get("ticket") if isinstance(data, dict) else None
        if not isinstance(ticket, dict):
            raise RuntimeError("Freshservice ticket response is invalid")
        return ticket

    async def fetch_ticket_details(self, external_id: str) -> ExternalTicket:
        """Fetch a lossless ticket body plus original ticket attachments."""
        raw = await self.fetch_ticket_raw(external_id, include_attachments=True)
        return self._parse_ticket(raw)

    async def download_attachment(self, download_url: str, max_bytes: int) -> bytes:
        """Download provider bytes with Freshservice auth and an explicit cap."""
        limit = max(1, int(max_bytes))
        current_url = str(download_url or "")
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            for _redirect in range(6):
                parsed = urllib.parse.urlparse(current_url)
                hostname = (parsed.hostname or "").lower().rstrip(".")
                provider_host = (
                    hostname == self.domain
                    or hostname.endswith(".freshservice.com")
                    or hostname.endswith(".freshworks.com")
                )
                credential_host = hostname == self.domain
                if (
                    parsed.scheme != "https"
                    or not hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("Freshservice attachment URL is not trusted")
                if not provider_host:
                    try:
                        addresses = {
                            item[4][0]
                            for item in socket.getaddrinfo(hostname, parsed.port or 443)
                        }
                    except socket.gaierror as exc:
                        raise ValueError(
                            "Freshservice attachment host could not be resolved"
                        ) from exc
                    if not addresses or any(
                        not ipaddress.ip_address(address).is_global
                        for address in addresses
                    ):
                        raise ValueError(
                            "Freshservice attachment URL targets a non-public host"
                        )
                elapsed = time.monotonic() - getattr(self, "_last_get_ts", 0.0)
                if provider_host and elapsed < self.min_interval_s:
                    await asyncio.sleep(self.min_interval_s - elapsed)
                auth = self._auth() if credential_host else None
                headers = self._headers() if credential_host else {}
                async with client.stream(
                    "GET", current_url, auth=auth, headers=headers
                ) as response:
                    if provider_host:
                        self._last_get_ts = time.monotonic()
                        self._capture_rate_limit(response)
                    if response.status_code == 429:
                        raise FreshserviceRateLimited(self._last_retry_after or 60.0)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise RuntimeError(
                                "Freshservice attachment redirect is missing a target"
                            )
                        current_url = urllib.parse.urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            if int(declared) > limit:
                                raise ValueError(
                                    "Freshservice attachment exceeds configured size limit"
                                )
                        except ValueError as exc:
                            if "exceeds" in str(exc):
                                raise
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > limit:
                            raise ValueError(
                                "Freshservice attachment exceeds configured size limit"
                            )
                    return bytes(content)
        raise RuntimeError("Freshservice attachment redirected too many times")

    def capability_manifest(self) -> dict[str, dict[str, Any]]:
        return {
            "integration.mode": {"status": "supported", "mode": "read_only"},
            "ticket.read": {"status": "supported", "scope": "freshservice.tickets.view"},
            "conversation.read": {
                "status": "supported",
                "scope": "freshservice.tickets.conversations.view",
            },
            "attachment.read": {
                "status": "supported",
                "scope": "freshservice.tickets.view",
            },
            "agent.read": {"status": "supported", "scope": "freshservice.agents.manage"},
            "group.read": {"status": "supported", "scope": "freshservice.agents.manage"},
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
            for key in (
                "ticket.read",
                "conversation.read",
                "agent.read",
                "group.read",
                "requester.read",
            ):
                manifest[key] = {**manifest[key], "status": "degraded", "detail": detail}
            return manifest

        async with httpx.AsyncClient(timeout=15) as client:
            probes = {
                "ticket.read": (f"{self.base_url}/api/v2/tickets", {"per_page": 1}),
                "agent.read": (f"{self.base_url}/api/v2/agents", {"per_page": 1, "active": "true"}),
                "group.read": (f"{self.base_url}/api/v2/groups", {"per_page": 1}),
                "requester.read": (f"{self.base_url}/api/v2/requesters", {"per_page": 1}),
            }
            conversation_ticket_id = None
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
                    if capability == "ticket.read" and response.status_code < 400:
                        payload = response.json()
                        rows = payload.get("tickets", []) if isinstance(payload, dict) else []
                        if rows and isinstance(rows[0], dict) and rows[0].get("id"):
                            conversation_ticket_id = str(rows[0]["id"])
                except Exception as exc:
                    manifest[capability] = {
                        **manifest[capability],
                        "status": "degraded",
                        "detail": type(exc).__name__,
                    }
            if conversation_ticket_id:
                try:
                    response = await self._rate_limited_get(
                        client,
                        f"{self.base_url}/api/v2/tickets/"
                        f"{conversation_ticket_id}/conversations",
                        {"per_page": 1},
                    )
                    if response.status_code < 400:
                        status = "supported"
                    elif response.status_code in {401, 403}:
                        status = "restricted"
                    elif response.status_code == 429:
                        status = "degraded"
                    else:
                        status = "unsupported"
                    manifest["conversation.read"] = {
                        **manifest["conversation.read"],
                        "status": status,
                        "http_status": response.status_code,
                    }
                except Exception as exc:
                    manifest["conversation.read"] = {
                        **manifest["conversation.read"],
                        "status": "degraded",
                        "detail": type(exc).__name__,
                    }
            else:
                manifest["conversation.read"] = {
                    **manifest["conversation.read"],
                    "status": "unknown",
                    "detail": "no_ticket_available_for_probe",
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
