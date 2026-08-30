"""Safe, data-driven routing guidance layered over the core AI contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import RoutingRuleRecord


MAX_ACTIVE_RULES = 100
EMPTY_RULES_FINGERPRINT = "sha256:" + hashlib.sha256(b"[]").hexdigest()
_POSTGRES_POLICY_LOCK_KEY = 607466365282548465  # stable Tickety routing-policy key


def lock_policy_for_write(db: Session) -> None:
    """Serialize route persistence with policy edits on PostgreSQL."""
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _POSTGRES_POLICY_LOCK_KEY},
        )


def rule_snapshot(rule: RoutingRuleRecord) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "enabled": bool(rule.enabled),
        "priority": rule.priority,
        "scope": rule.scope,
        "service_contains": rule.service_contains,
        "failure_domain_contains": rule.failure_domain_contains,
        "primary_group": rule.primary_group,
        "secondary_group": rule.secondary_group,
        "version": rule.version,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def active_rule_payloads(db: Session) -> list[dict[str, Any]]:
    """Return bounded structured rules; free-form labels never reach the model."""
    rows = db.query(RoutingRuleRecord).filter(
        RoutingRuleRecord.enabled.is_(True)
    ).order_by(
        RoutingRuleRecord.priority.asc(),
        RoutingRuleRecord.id.asc(),
    ).limit(MAX_ACTIVE_RULES).all()
    return [
        {
            "priority": row.priority,
            "when": {
                key: value
                for key, value in {
                    "scope": row.scope,
                    "affected_service_contains": row.service_contains,
                    "failure_domain_contains": row.failure_domain_contains,
                }.items()
                if value is not None
            },
            "recommend": {
                "primary_group": row.primary_group,
                "secondary_group": row.secondary_group,
            },
        }
        for row in rows
    ]


def rules_fingerprint(db: Session) -> str:
    return payload_fingerprint(active_rule_payloads(db))


def payload_fingerprint(payload: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
