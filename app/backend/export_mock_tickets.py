import argparse
import asyncio
import os
from typing import Any

import httpx

from . import settings as settings_module
from .integrations.freshservice import FreshserviceAdapter
from .seed import TICKETS


def _freshservice_subject(ticket: dict[str, Any]) -> str:
    return ticket["subject"]


def _freshservice_description(ticket: dict[str, Any]) -> str:
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
        f"Created at: {ticket.get('created_at')}",
        f"Due by: {ticket.get('due_by')}",
        f"Related tags: {ticket.get('tags')}",
    ]
    if ticket.get("ai_reasoning"):
        lines.extend(["", f"AI reasoning: {ticket['ai_reasoning']}"])
    return "\n".join(str(line) for line in lines if line is not None)


def _ticket_payload(adapter: FreshserviceAdapter, ticket: dict[str, Any], source: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subject": _freshservice_subject(ticket),
        "description": _freshservice_description(ticket),
        "email": ticket.get("reporter") or "tickety-demo@example.com",
        "priority": adapter.to_freshservice_priority(ticket.get("priority")),
        "status": adapter.to_freshservice_status(ticket.get("external_status") or ticket.get("status")),
        "source": source,
    }
    workspace_id = os.getenv("FRESHSERVICE_WORKSPACE_ID", "").strip()
    if workspace_id and workspace_id != "0":
        payload["workspace_id"] = int(workspace_id) if workspace_id.isdigit() else workspace_id
    return payload


async def _existing_subjects(adapter: FreshserviceAdapter) -> set[str]:
    existing = await adapter.fetch_tickets_since(None)
    return {ticket.subject for ticket in existing}


async def export_seed_tickets(dry_run: bool, dedupe: bool, source: int) -> dict[str, Any]:
    settings_module.load_settings_into_env()
    adapter = FreshserviceAdapter()
    if not adapter.domain or adapter.domain == "yourdomain.freshservice.com":
        raise RuntimeError("FRESHSERVICE_DOMAIN is not configured")
    if not adapter.oauth_access_token and (not adapter.api_key or adapter.api_key == "dummy-key"):
        raise RuntimeError("FRESHSERVICE_API_KEY or FRESHSERVICE_OAUTH_ACCESS_TOKEN is not configured")

    existing_subjects = await _existing_subjects(adapter) if dedupe else set()
    result: dict[str, Any] = {
        "domain": adapter.domain,
        "dry_run": dry_run,
        "created": 0,
        "skipped": 0,
        "errors": 0,
        "tickets": [],
    }

    for ticket in TICKETS:
        subject = _freshservice_subject(ticket)
        if subject in existing_subjects:
            result["skipped"] += 1
            result["tickets"].append({"tickety_id": ticket["id"], "action": "skipped", "subject": subject})
            continue

        payload = _ticket_payload(adapter, ticket, source)
        if dry_run:
            result["tickets"].append({"tickety_id": ticket["id"], "action": "dry-run", "payload": payload})
            continue

        try:
            created = await adapter.create_ticket(payload)
        except httpx.HTTPStatusError as exc:
            if payload.get("status") != 2 and exc.response.status_code == 400:
                retry_payload = dict(payload)
                retry_payload["status"] = 2
                retry_payload["description"] += "\n\nFreshservice creation fallback: created as Open."
                created = await adapter.create_ticket(retry_payload)
                payload = retry_payload
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
            "freshservice_id": created.get("id"),
            "freshservice_url": adapter.build_ticket_url(str(created.get("id", ""))) if created.get("id") else None,
            "status": payload.get("status"),
        })
        existing_subjects.add(subject)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Tickety seed tickets to Freshservice.")
    parser.add_argument("--domain", help="Freshservice domain, e.g. situstudio.freshservice.com")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without creating tickets")
    parser.add_argument("--no-dedupe", action="store_true", help="Create tickets without checking existing subjects")
    parser.add_argument("--source", type=int, default=2, help="Freshservice source id. Default: 2")
    args = parser.parse_args()

    if args.domain:
        os.environ["FRESHSERVICE_DOMAIN"] = args.domain

    result = asyncio.run(export_seed_tickets(
        dry_run=args.dry_run,
        dedupe=not args.no_dedupe,
        source=args.source,
    ))

    print(f"Freshservice domain: {result['domain']}")
    print(f"Created: {result['created']} | Skipped: {result['skipped']} | Errors: {result['errors']}")
    for item in result["tickets"]:
        if item["action"] == "created":
            print(f"created {item['tickety_id']} -> {item.get('freshservice_url')}")
        elif item["action"] == "skipped":
            print(f"skipped {item['tickety_id']} already exists")
        elif item["action"] == "dry-run":
            print(f"dry-run {item['tickety_id']} -> {item['payload']['subject']}")
        else:
            print(f"error {item['tickety_id']} status={item.get('status_code')} {item.get('error')}")

    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
