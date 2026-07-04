import argparse
import asyncio
import os
from typing import Any

import httpx

from . import settings as settings_module
from .integrations.jira import JiraAdapter
from .seed import TICKETS


LEGACY_SUBJECT_PREFIX = "[Tickety mock {id}]"
LEGACY_LABEL = "tickety-mock"


def _jira_subject(ticket: dict[str, Any]) -> str:
    return ticket["subject"]


def _legacy_jira_subject(ticket: dict[str, Any]) -> str:
    return f"{LEGACY_SUBJECT_PREFIX.format(id=ticket['id'])} {ticket['subject']}"


def _jira_description(ticket: dict[str, Any]) -> str:
    lines = [
        ticket.get("description") or "",
        "",
        "---",
        "Request details",
        f"Reporter: {ticket.get('reporter')}",
        f"Ticket type: {ticket.get('ticket_type')}",
        f"Status: {ticket.get('status')}",
        f"Priority: {ticket.get('priority')}",
        f"Category: {ticket.get('category')}",
        f"Impact: {ticket.get('impact')}",
        f"Urgency: {ticket.get('urgency')}",
        f"Sentiment: {ticket.get('sentiment')}",
        f"Mood: {ticket.get('mood')}",
        f"Complexity: {ticket.get('complexity')}",
        f"Requested at: {ticket.get('created_at')}",
        f"Last activity: {ticket.get('updated_at')}",
        f"Due by: {ticket.get('due_by')}",
        f"Related tags: {ticket.get('tags')}",
    ]
    if ticket.get("ai_reasoning"):
        lines.extend(["", f"AI reasoning: {ticket['ai_reasoning']}"])
    return "\n".join(str(line) for line in lines if line is not None)


def _jira_label(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    return "-".join(part for part in clean.split("-") if part)[:255] or "tickety"


def _jira_date(value: Any) -> str | None:
    if not value:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else None


def _issue_payload(
    adapter: JiraAdapter,
    ticket: dict[str, Any],
    project_key: str,
    issue_type: str,
    include_priority: bool,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "summary": _jira_subject(ticket),
        "description": adapter.text_to_adf(_jira_description(ticket)),
        "issuetype": {"name": issue_type},
        "labels": [
            _jira_label(ticket.get("ticket_type")),
            _jira_label(ticket.get("category")),
            _jira_label(ticket.get("priority")),
            _jira_label(ticket.get("impact")),
            _jira_label(ticket.get("urgency")),
        ],
    }
    due_date = _jira_date(ticket.get("due_by"))
    if due_date:
        fields["duedate"] = due_date
    if include_priority:
        fields["priority"] = {"name": adapter.to_jira_priority(ticket.get("priority"))}
    return {"fields": fields}


async def _existing_issue_subjects(adapter: JiraAdapter, project_key: str) -> set[str]:
    issues = await adapter.search_issues(
        f'project = "{project_key}" ORDER BY created DESC',
        max_results=250,
    )
    return {issue.subject for issue in issues}


async def export_seed_tickets(
    dry_run: bool,
    dedupe: bool,
    project_key: str | None,
    issue_type: str | None,
    include_priority: bool,
) -> dict[str, Any]:
    settings_module.load_settings_into_env()
    adapter = JiraAdapter()
    project_key = (project_key or adapter.project_key or "").strip()
    if not project_key and not dry_run:
        project_key = await adapter.default_project_key()
    if not project_key:
        project_key = "PROJECT"
    issue_type = (issue_type or adapter.issue_type or "Task").strip()

    existing_subjects = await _existing_issue_subjects(adapter, project_key) if dedupe and not dry_run else set()
    result: dict[str, Any] = {
        "base_url": adapter.base_url,
        "project_key": project_key,
        "issue_type": issue_type,
        "dry_run": dry_run,
        "created": 0,
        "skipped": 0,
        "errors": 0,
        "tickets": [],
    }

    for ticket in TICKETS:
        subject = _jira_subject(ticket)
        if subject in existing_subjects or _legacy_jira_subject(ticket) in existing_subjects:
            result["skipped"] += 1
            result["tickets"].append({"tickety_id": ticket["id"], "action": "skipped", "subject": subject})
            continue

        payload = _issue_payload(adapter, ticket, project_key, issue_type, include_priority)
        if dry_run:
            result["tickets"].append({"tickety_id": ticket["id"], "action": "dry-run", "payload": payload})
            continue

        try:
            created = await adapter.create_issue(payload)
        except httpx.HTTPStatusError as exc:
            # Some Jira screens do not allow setting priority during create.
            if include_priority and exc.response.status_code == 400:
                retry_payload = _issue_payload(adapter, ticket, project_key, issue_type, include_priority=False)
                try:
                    created = await adapter.create_issue(retry_payload)
                except httpx.HTTPStatusError as retry_exc:
                    result["errors"] += 1
                    result["tickets"].append({
                        "tickety_id": ticket["id"],
                        "action": "error",
                        "subject": subject,
                        "status_code": retry_exc.response.status_code,
                        "error": retry_exc.response.text,
                    })
                    continue
            else:
                result["errors"] += 1
                result["tickets"].append({
                    "tickety_id": ticket["id"],
                    "action": "error",
                    "subject": subject,
                    "status_code": exc.response.status_code,
                    "error": exc.response.text,
                })
                continue

        result["created"] += 1
        result["tickets"].append({
            "tickety_id": ticket["id"],
            "action": "created",
            "subject": subject,
            "jira_key": created.get("key"),
            "jira_url": adapter.build_ticket_url(str(created.get("key", ""))) if created.get("key") else None,
        })
        existing_subjects.add(subject)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export seed tickets to Jira.")
    parser.add_argument("--base-url", help="Jira Cloud base URL, e.g. https://situstudio.atlassian.net")
    parser.add_argument("--project-key", help="Jira project key. Falls back to JIRA_PROJECT_KEY or first visible project.")
    parser.add_argument("--issue-type", help="Jira issue type name. Defaults to JIRA_ISSUE_TYPE or Task.")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without creating issues")
    parser.add_argument("--no-dedupe", action="store_true", help="Create issues without checking existing summaries")
    parser.add_argument("--no-priority", action="store_true", help="Do not set Jira priority during issue creation")
    args = parser.parse_args()

    if args.base_url:
        os.environ["JIRA_BASE_URL"] = args.base_url

    result = asyncio.run(export_seed_tickets(
        dry_run=args.dry_run,
        dedupe=not args.no_dedupe,
        project_key=args.project_key,
        issue_type=args.issue_type,
        include_priority=not args.no_priority,
    ))

    print(f"Jira site: {result['base_url']}")
    print(f"Project: {result['project_key']} | Issue type: {result['issue_type']}")
    print(f"Created: {result['created']} | Skipped: {result['skipped']} | Errors: {result['errors']}")
    for item in result["tickets"]:
        if item["action"] == "created":
            print(f"created {item['tickety_id']} -> {item.get('jira_url')}")
        elif item["action"] == "skipped":
            print(f"skipped {item['tickety_id']} already exists")
        elif item["action"] == "dry-run":
            print(f"dry-run {item['tickety_id']} -> {item['payload']['fields']['summary']}")
        else:
            print(f"error {item['tickety_id']} status={item.get('status_code')} {item.get('error')}")

    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
