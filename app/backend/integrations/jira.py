import base64
import os
import urllib.parse
from datetime import datetime
from typing import List, Optional

import httpx

from ..schema import ExternalTicket, WebhookEvent
from .base import BaseITSMAdapter


JIRA_PRIORITY_TO_TICKETY = {
    "highest": "P1",
    "high": "P2",
    "medium": "P3",
    "low": "P4",
    "lowest": "P4",
}

TICKETY_PRIORITY_TO_JIRA = {
    "P1": "Highest",
    "P2": "High",
    "P3": "Medium",
    "P4": "Low",
}


class JiraAdapter(BaseITSMAdapter):
    provider_name = "jira"

    def __init__(self):
        self.base_url = self._normalize_base_url(os.getenv("JIRA_BASE_URL") or "https://your-site.atlassian.net")
        self.email = os.getenv("JIRA_EMAIL", "")
        self.api_token = os.getenv("JIRA_API_TOKEN", "")
        self.project_key = self._normalize_optional(os.getenv("JIRA_PROJECT_KEY", ""))
        self.issue_type = os.getenv("JIRA_ISSUE_TYPE", "Task").strip() or "Task"

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        value = (value or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
        return f"{parsed.scheme}://{parsed.netloc or parsed.path}".rstrip("/")

    @staticmethod
    def _normalize_optional(value: str) -> str:
        value = (value or "").strip()
        if value.lower() in {"your-project-key", "project", "none", "null"}:
            return ""
        return value

    def _headers(self) -> dict:
        token = base64.b64encode(f"{self.email}:{self.api_token}".encode("utf-8")).decode("ascii")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}",
        }

    def _assert_configured(self) -> None:
        missing = [
            name for name, value in (
                ("JIRA_BASE_URL", self.base_url),
                ("JIRA_EMAIL", self.email),
                ("JIRA_API_TOKEN", self.api_token),
            )
            if not value or value == "https://your-site.atlassian.net"
        ]
        if missing:
            raise RuntimeError(f"Missing Jira configuration: {', '.join(missing)}")

    def map_priority(self, external_priority) -> str:
        key = str(external_priority or "").strip().lower()
        return JIRA_PRIORITY_TO_TICKETY.get(key, "P3")

    def to_jira_priority(self, tickety_priority) -> str:
        key = str(tickety_priority or "P3").strip().upper()
        return TICKETY_PRIORITY_TO_JIRA.get(key, "Medium")

    def map_status(self, external_status) -> str:
        status = str(external_status or "Open").strip()
        if status.lower() in {"done", "closed", "resolved"}:
            return "Closed"
        return status or "Open"

    def build_ticket_url(self, external_id: str) -> str:
        return f"{self.base_url}/browse/{external_id}"

    @staticmethod
    def _parse_datetime(value) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    @staticmethod
    def text_to_adf(text: str) -> dict:
        paragraphs = []
        for raw_line in (text or "").splitlines() or [""]:
            if raw_line:
                paragraphs.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": raw_line}],
                })
            else:
                paragraphs.append({"type": "paragraph", "content": []})
        return {"type": "doc", "version": 1, "content": paragraphs}

    @staticmethod
    def adf_to_text(value) -> str:
        if isinstance(value, str):
            return value
        out: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "text" and node.get("text"):
                    out.append(node["text"])
                for child in node.get("content") or []:
                    walk(child)
                if node.get("type") == "paragraph":
                    out.append("\n")
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return "".join(out).strip()

    def _parse_issue(self, raw: dict) -> ExternalTicket:
        fields = raw.get("fields") or {}
        priority = fields.get("priority") or {}
        status = fields.get("status") or {}
        reporter = fields.get("reporter") or {}
        assignee = fields.get("assignee") or {}
        issuetype = fields.get("issuetype") or {}
        return ExternalTicket(
            external_id=str(raw.get("key") or raw.get("id") or ""),
            subject=fields.get("summary") or "(no summary)",
            description=self.adf_to_text(fields.get("description")),
            reporter=reporter.get("emailAddress") or reporter.get("displayName") or "",
            priority=self.map_priority(priority.get("name")),
            status=self.map_status(status.get("name")),
            assignee_id=assignee.get("accountId"),
            updated_at=self._parse_datetime(fields.get("updated")),
            created_at=self._parse_datetime(fields.get("created")),
            due_by=self._parse_datetime(fields.get("duedate")),
            ticket_type=issuetype.get("name"),
            url=self.build_ticket_url(str(raw.get("key") or "")),
        )

    def _parse_issue_batch(self, raw_issues: list) -> List[ExternalTicket]:
        """Validate issues independently so malformed requester content cannot
        abort a whole provider page."""
        parsed: List[ExternalTicket] = []
        for raw in raw_issues:
            try:
                parsed.append(self._parse_issue(raw))
            except Exception as exc:
                print(
                    "[Jira] ticket parse skipped "
                    f"kind={type(exc).__name__}"
                )
        return parsed

    async def fetch_new_tickets(self, since: Optional[datetime] = None) -> List[ExternalTicket]:
        return await self.fetch_tickets_since(since)

    async def fetch_updated_tickets(self, since: datetime) -> List[ExternalTicket]:
        return await self.fetch_tickets_since(since)

    async def fetch_tickets_since(self, since: Optional[datetime], max_pages: Optional[int] = None) -> List[ExternalTicket]:
        self._assert_configured()
        project = self.project_key
        if not project:
            project = await self.default_project_key()
        jql = f'project = "{project}"'
        if since:
            jql += f' AND updated >= "{since.strftime("%Y-%m-%d %H:%M")}"'
        jql += " ORDER BY updated ASC"
        pages = max(1, max_pages or 50)
        return await self.search_issues(jql, max_results=100 * pages, max_pages=pages)

    async def search_issues(self, jql: str, max_results: int = 100, max_pages: int = 50) -> List[ExternalTicket]:
        self._assert_configured()
        out: list[ExternalTicket] = []
        next_page_token = None
        total_cap = max(1, max_results)
        page_cap = max(1, max_pages)
        async with httpx.AsyncClient(timeout=30) as client:
            page = 0
            while len(out) < total_cap and page < page_cap:
                payload = {
                    "jql": jql,
                    "maxResults": min(100, total_cap - len(out)),
                    "fields": ["summary", "description", "priority", "status", "reporter", "assignee", "updated", "created", "duedate", "issuetype"],
                }
                if next_page_token:
                    payload["nextPageToken"] = next_page_token
                resp = await client.post(
                    f"{self.base_url}/rest/api/3/search/jql",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise RuntimeError("Jira search response must be an object")
                issues = data.get("issues", [])
                if not isinstance(issues, list):
                    raise RuntimeError("Jira issues must be a list")
                out.extend(self._parse_issue_batch(issues))
                next_page_token = data.get("nextPageToken")
                if data.get("isLast") or not next_page_token or not issues:
                    break
                page += 1
        return out

    async def default_project_key(self) -> str:
        self._assert_configured()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/rest/api/3/project/search",
                headers=self._headers(),
                params={"maxResults": 1},
            )
            resp.raise_for_status()
            projects = resp.json().get("values") or []
            if not projects:
                raise RuntimeError("No Jira projects are visible to this API token")
            return projects[0]["key"]

    async def fetch_agents(self, max_pages: Optional[int] = None) -> List[dict]:
        self._assert_configured()
        project = self.project_key
        if not project:
            try:
                project = await self.default_project_key()
            except Exception:
                project = ""
        users: list[dict] = []
        if project:
            try:
                users = await self._fetch_user_pages(
                    "/rest/api/3/user/assignable/search",
                    {"project": project},
                    max_pages=max_pages,
                )
            except httpx.HTTPError:
                users = []
        if not users:
            users = await self._fetch_user_pages(
                "/rest/api/3/users/search",
                {},
                max_pages=max_pages,
            )
        return [self._normalize_agent(u) for u in users]

    async def _fetch_user_pages(
        self,
        path: str,
        params: dict,
        max_pages: Optional[int] = None,
    ) -> List[dict]:
        out: list[dict] = []
        page_size = 100
        page = 0
        cap = max_pages if max_pages is not None else 50
        async with httpx.AsyncClient(timeout=30) as client:
            while page < cap:
                page_params = {
                    **params,
                    "startAt": page * page_size,
                    "maxResults": page_size,
                }
                resp = await client.get(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    params=page_params,
                )
                resp.raise_for_status()
                batch = resp.json()
                if not isinstance(batch, list):
                    break
                out.extend(batch)
                if len(batch) < page_size:
                    break
                page += 1
        return out

    @staticmethod
    def _normalize_agent(raw: dict) -> dict:
        display_name = raw.get("displayName") or raw.get("name") or raw.get("emailAddress") or ""
        return {
            "id": raw.get("accountId") or raw.get("key") or raw.get("name") or "",
            "name": display_name,
            "display_name": display_name,
            "email": raw.get("emailAddress") or "",
            "job_title": raw.get("accountType") or "Jira user",
            "active": raw.get("active") is not False,
        }

    async def create_issue(self, payload: dict) -> dict:
        self._assert_configured()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/rest/api/3/issue",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def update_issue(self, issue_key: str, payload: dict) -> None:
        self._assert_configured()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{self.base_url}/rest/api/3/issue/{issue_key}",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()

    def parse_webhook(
        self,
        payload: dict,
        headers: dict,
        raw_body: bytes | None = None,
    ) -> Optional[WebhookEvent]:
        issue = payload.get("issue") or {}
        key = issue.get("key")
        if not key:
            return None
        return WebhookEvent(
            event_type=payload.get("webhookEvent") or "issue_updated",
            external_id=str(key),
            raw=payload,
        )
