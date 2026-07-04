import argparse
import asyncio
import os
from typing import Any

import httpx

from . import settings as settings_module
from .export_mock_tickets_jira import (
    LEGACY_LABEL,
    _issue_payload,
    _jira_subject,
    _legacy_jira_subject,
)
from .integrations.jira import JiraAdapter
from .seed import TICKETS


async def normalize_jira_seed_tickets(
    dry_run: bool,
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

    tickets_by_legacy_subject = {_legacy_jira_subject(ticket): ticket for ticket in TICKETS}
    tickets_by_subject = {_jira_subject(ticket): ticket for ticket in TICKETS}
    issues = await adapter.search_issues(
        f'project = "{project_key}" ORDER BY created ASC',
        max_results=250,
    )

    result: dict[str, Any] = {
        "base_url": adapter.base_url,
        "project_key": project_key,
        "issue_type": issue_type,
        "dry_run": dry_run,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "issues": [],
    }

    for issue in issues:
        ticket = tickets_by_legacy_subject.get(issue.subject) or tickets_by_subject.get(issue.subject)
        if not ticket:
            result["skipped"] += 1
            result["issues"].append({"jira_key": issue.external_id, "action": "skipped", "subject": issue.subject})
            continue

        payload = _issue_payload(adapter, ticket, project_key, issue_type, include_priority)
        # Jira does not allow changing issue type through the general edit endpoint.
        payload["fields"].pop("project", None)
        payload["fields"].pop("issuetype", None)
        if dry_run:
            result["issues"].append({
                "jira_key": issue.external_id,
                "action": "dry-run",
                "subject": payload["fields"]["summary"],
            })
            continue

        try:
            await adapter.update_issue(issue.external_id, payload)
        except httpx.HTTPStatusError as exc:
            if include_priority and exc.response.status_code == 400:
                retry_payload = _issue_payload(adapter, ticket, project_key, issue_type, include_priority=False)
                retry_payload["fields"].pop("project", None)
                retry_payload["fields"].pop("issuetype", None)
                try:
                    await adapter.update_issue(issue.external_id, retry_payload)
                except httpx.HTTPStatusError as retry_exc:
                    result["errors"] += 1
                    result["issues"].append({
                        "jira_key": issue.external_id,
                        "action": "error",
                        "status_code": retry_exc.response.status_code,
                        "error": retry_exc.response.text,
                    })
                    continue
            else:
                result["errors"] += 1
                result["issues"].append({
                    "jira_key": issue.external_id,
                    "action": "error",
                    "status_code": exc.response.status_code,
                    "error": exc.response.text,
                })
                continue

        result["updated"] += 1
        result["issues"].append({
            "jira_key": issue.external_id,
            "action": "updated",
            "subject": payload["fields"]["summary"],
            "jira_url": adapter.build_ticket_url(issue.external_id),
        })

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize seeded Jira tickets so they read like real ITSM records.")
    parser.add_argument("--base-url", help="Jira Cloud base URL, e.g. https://situstudio.atlassian.net")
    parser.add_argument("--project-key", help="Jira project key. Falls back to JIRA_PROJECT_KEY or first visible project.")
    parser.add_argument("--issue-type", help="Jira issue type name. Defaults to JIRA_ISSUE_TYPE or Task.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned updates without editing issues")
    parser.add_argument("--no-priority", action="store_true", help="Do not set Jira priority during issue updates")
    args = parser.parse_args()

    if args.base_url:
        os.environ["JIRA_BASE_URL"] = args.base_url

    result = asyncio.run(normalize_jira_seed_tickets(
        dry_run=args.dry_run,
        project_key=args.project_key,
        issue_type=args.issue_type,
        include_priority=not args.no_priority,
    ))

    print(f"Jira site: {result['base_url']}")
    print(f"Project: {result['project_key']} | Issue type: {result['issue_type']}")
    print(f"Updated: {result['updated']} | Skipped: {result['skipped']} | Errors: {result['errors']}")
    for item in result["issues"]:
        if item["action"] == "updated":
            print(f"updated {item['jira_key']} -> {item.get('jira_url')}")
        elif item["action"] == "dry-run":
            print(f"dry-run {item['jira_key']} -> {item['subject']}")
        elif item["action"] == "skipped":
            print(f"skipped {item['jira_key']} {item.get('subject')}")
        else:
            print(f"error {item.get('jira_key')} status={item.get('status_code')} {item.get('error')}")

    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
