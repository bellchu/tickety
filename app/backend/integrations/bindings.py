import json
import os
import re
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..database import (
    IntegrationAuditRecord,
    IntegrationBindingRecord,
    IntegrationCapabilityRecord,
)
from .registry import clear_adapter_cache, get_adapter


BINDING_ENVIRONMENTS = {"trial", "sandbox", "production"}
BINDING_STATES = {"draft", "validating", "active", "suspended", "expired", "retired"}
CAPABILITY_STATUSES = {"supported", "unsupported", "restricted", "unknown", "degraded"}
ALLOWED_CREDENTIAL_REFERENCES = {"env://freshservice"}
REQUIRED_ACTIVATION_CAPABILITIES = {"ticket.read"}


class BindingValidationError(ValueError):
    pass


def _utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize API datetimes to the database's UTC-naive convention."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def deployment_class() -> str:
    value = (os.getenv("TICKETY_DEPLOYMENT_CLASS") or "production").strip().lower()
    if value not in {"poc", "production"}:
        raise BindingValidationError("TICKETY_DEPLOYMENT_CLASS must be poc or production")
    return value


def normalize_freshservice_host(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise BindingValidationError("Freshservice account host is required")
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise BindingValidationError("Freshservice account host must be an HTTPS hostname")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise BindingValidationError("Freshservice account host must not include a path or query")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host.endswith(".freshservice.com") or host == "freshservice.com":
        raise BindingValidationError("Freshservice account host is not allowed")
    if len(host) > 255:
        raise BindingValidationError("Freshservice account host is too long")
    return host


def _workspace_ids(values: Optional[list[str]]) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        item = str(value).strip()
        if not item or len(item) > 255 or item in normalized:
            continue
        normalized.append(item)
    return normalized


def _audit(
    db: Session,
    binding_id: str,
    action: str,
    actor_id: Optional[str],
    details: Optional[dict[str, Any]] = None,
) -> None:
    db.add(IntegrationAuditRecord(
        binding_id=binding_id,
        action=action,
        actor_id=actor_id,
        details=json.dumps(details or {}, sort_keys=True, separators=(",", ":")),
    ))


def validate_automatic_ai_rollout_evidence(
    db: Session,
    binding: IntegrationBindingRecord,
) -> None:
    """Fail closed unless the latest audited projection gates are complete."""
    actions = (
        "automatic_ai.rollout.phase0.approved",
        "automatic_ai.rollout.phase1.approved",
        "automatic_ai.rollout.phase2.approved",
    )
    rows = db.query(IntegrationAuditRecord).filter(
        IntegrationAuditRecord.binding_id == binding.id,
        IntegrationAuditRecord.action.in_(actions),
    ).order_by(IntegrationAuditRecord.created_at.desc()).all()
    latest: dict[str, IntegrationAuditRecord] = {}
    for row in rows:
        latest.setdefault(row.action, row)
    if set(latest) != set(actions):
        raise BindingValidationError("automatic_ai_rollout_evidence_missing")
    try:
        evidence = {
            action: json.loads(latest[action].details or "{}")
            for action in actions
        }
        common_valid = all(
            latest[action].actor_id
            and evidence[action].get("status") == "approved"
            and evidence[action].get("capability_version")
            == binding.capability_version
            and re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                str(evidence[action].get("evidence_digest") or ""),
            )
            for action in actions
        )
        phase0 = evidence[actions[0]]
        phase1 = evidence[actions[1]]
        phase2 = evidence[actions[2]]
        inventory_completed_at = datetime.fromisoformat(
            str(phase2["inventory_completed_at"]).replace("Z", "+00:00")
        )
        if inventory_completed_at.tzinfo is not None:
            inventory_completed_at = inventory_completed_at.astimezone(
                timezone.utc
            ).replace(tzinfo=None)
        inventory_age = datetime.utcnow() - inventory_completed_at
        valid = all((
            common_valid,
            phase0.get("schema_verified") is True,
            phase0.get("retention_verified") is True,
            phase0.get("read_only_verified") is True,
            phase0.get("negative_egress_passed") is True,
            float(phase1.get("duration_hours", 0)) >= 24,
            bool(phase1.get("all_tickets"))
            or int(phase1.get("reconciliations", 0)) >= 100,
            int(phase1.get("critical_errors", -1)) == 0,
            float(phase1.get("identity_hash_coverage", 0)) == 1.0,
            float(phase1.get("projection_failure_rate", 1)) <= 0.01,
            float(phase2.get("duration_hours", 0)) >= 24,
            bool(phase2.get("all_revisions"))
            or int(phase2.get("revisions", 0)) >= 100,
            float(phase2.get("eligibility_agreement", 0)) == 1.0,
            int(phase2.get("historical_seed_claims", -1)) == 0,
            phase2.get("two_worker_equal") is True,
            phase2.get("inventory_complete") is True,
            timedelta(0) <= inventory_age <= timedelta(minutes=15),
        ))
    except (KeyError, TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise BindingValidationError(
            "automatic_ai_rollout_evidence_invalid_or_stale"
        )


def create_binding(
    db: Session,
    *,
    provider: str,
    environment: str,
    canonical_account_host: str,
    workspace_ids: Optional[list[str]],
    installation_id: Optional[str],
    product_variant: Optional[str],
    credential_reference: str,
    expires_at: Optional[datetime],
    actor_id: Optional[str],
) -> IntegrationBindingRecord:
    provider = (provider or "").strip().lower()
    environment = (environment or "").strip().lower()
    if provider != "freshservice":
        raise BindingValidationError("Only Freshservice bindings are supported")
    if environment not in BINDING_ENVIRONMENTS:
        raise BindingValidationError("Unsupported integration environment")
    if credential_reference not in ALLOWED_CREDENTIAL_REFERENCES:
        raise BindingValidationError("Unsupported credential reference")
    if environment in {"trial", "sandbox"} and deployment_class() != "poc":
        raise BindingValidationError("Trial and sandbox bindings require a POC deployment")
    if environment == "production" and deployment_class() != "production":
        raise BindingValidationError("Production bindings require a production deployment")
    expires_at = _utc_naive(expires_at)
    now = datetime.utcnow()
    if environment == "trial":
        if not expires_at or expires_at <= now:
            raise BindingValidationError("Trial binding expiry must be in the future")
        if expires_at > now + timedelta(days=21):
            raise BindingValidationError("Trial binding expiry exceeds the allowed POC window")

    host = normalize_freshservice_host(canonical_account_host)
    install = (installation_id or "").strip() or None
    if install and len(install) > 255:
        raise BindingValidationError("Installation ID is too long")
    variant = (product_variant or "").strip().upper() or None
    if variant not in {None, "ITSM", "MSP"}:
        raise BindingValidationError("Product variant must be ITSM or MSP")

    record = IntegrationBindingRecord(
        id=str(uuid.uuid4()),
        provider=provider,
        environment=environment,
        state="draft",
        canonical_account_host=host,
        installation_id=install,
        workspace_ids=json.dumps(_workspace_ids(workspace_ids), separators=(",", ":")),
        product_variant=variant,
        credential_reference=credential_reference,
        expires_at=expires_at,
    )
    db.add(record)
    db.flush()
    _audit(db, record.id, "binding.created", actor_id, {
        "provider": provider,
        "environment": environment,
        "host": host,
    })
    db.commit()
    db.refresh(record)
    return record


def get_binding(db: Session, binding_id: str) -> Optional[IntegrationBindingRecord]:
    return db.query(IntegrationBindingRecord).filter(
        IntegrationBindingRecord.id == binding_id
    ).first()


def get_active_binding(
    db: Session, provider: Optional[str] = None
) -> Optional[IntegrationBindingRecord]:
    query = db.query(IntegrationBindingRecord).filter(
        IntegrationBindingRecord.state == "active"
    )
    if provider:
        query = query.filter(IntegrationBindingRecord.provider == provider)
    return query.order_by(IntegrationBindingRecord.activated_at.desc()).first()


def list_capabilities(db: Session, binding_id: str) -> list[IntegrationCapabilityRecord]:
    return db.query(IntegrationCapabilityRecord).filter(
        IntegrationCapabilityRecord.binding_id == binding_id
    ).order_by(IntegrationCapabilityRecord.capability).all()


async def validate_binding(
    db: Session,
    binding: IntegrationBindingRecord,
    *,
    actor_id: Optional[str],
) -> dict[str, Any]:
    if binding.state in {"retired", "expired"}:
        raise BindingValidationError("Expired or retired bindings cannot be validated")
    if binding.environment in {"trial", "sandbox"} and deployment_class() != "poc":
        raise BindingValidationError("Binding environment does not match deployment class")
    if binding.environment == "production" and deployment_class() != "production":
        raise BindingValidationError("Binding environment does not match deployment class")
    if binding.expires_at and binding.expires_at <= datetime.utcnow():
        binding.state = "expired"
        _audit(db, binding.id, "binding.expired", actor_id)
        db.commit()
        raise BindingValidationError("Binding has expired")

    binding.state = "validating"
    db.commit()
    clear_adapter_cache(binding.id)
    adapter = get_adapter(binding=binding)
    observed = await adapter.probe_capabilities()

    checked_at = datetime.utcnow()
    for capability, payload in observed.items():
        status = str(payload.get("status") or "unknown").lower()
        if status not in CAPABILITY_STATUSES:
            status = "unknown"
        row = db.query(IntegrationCapabilityRecord).filter(
            IntegrationCapabilityRecord.binding_id == binding.id,
            IntegrationCapabilityRecord.capability == capability,
        ).first()
        if row is None:
            row = IntegrationCapabilityRecord(
                binding_id=binding.id,
                capability=capability,
                status=status,
            )
            db.add(row)
        row.status = status
        row.details = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        row.checked_at = checked_at

    ready = all(
        str((observed.get(capability) or {}).get("status")) == "supported"
        for capability in REQUIRED_ACTIVATION_CAPABILITIES
    )
    evidence = {
        "checked_capabilities": sorted(observed),
        "ready_for_activation": ready,
    }
    binding.validation_evidence = json.dumps(
        evidence, sort_keys=True, separators=(",", ":")
    )
    binding.capability_version += 1
    _audit(db, binding.id, "binding.validated", actor_id, evidence)
    db.commit()
    db.refresh(binding)
    return {"ready_for_activation": ready, "capabilities": observed}


def activate_binding(
    db: Session,
    binding: IntegrationBindingRecord,
    *,
    actor_id: Optional[str],
) -> IntegrationBindingRecord:
    if binding.state != "validating":
        raise BindingValidationError("Binding must be validated before activation")
    if binding.expires_at and binding.expires_at <= datetime.utcnow():
        raise BindingValidationError("Binding has expired")
    statuses = {
        row.capability: row.status for row in list_capabilities(db, binding.id)
    }
    missing = sorted(
        capability for capability in REQUIRED_ACTIVATION_CAPABILITIES
        if statuses.get(capability) != "supported"
    )
    if missing:
        raise BindingValidationError(
            "Required capabilities are not supported: " + ", ".join(missing)
        )
    other = db.query(IntegrationBindingRecord).filter(
        IntegrationBindingRecord.id != binding.id,
        IntegrationBindingRecord.provider == binding.provider,
        IntegrationBindingRecord.state == "active",
    ).first()
    if other:
        raise BindingValidationError("Another binding is already active in this deployment")
    binding.state = "active"
    binding.activated_by = actor_id
    binding.activated_at = datetime.utcnow()
    binding.suspended_at = None
    _audit(db, binding.id, "binding.activated", actor_id)
    db.commit()
    db.refresh(binding)
    return binding


def suspend_binding(
    db: Session,
    binding: IntegrationBindingRecord,
    *,
    actor_id: Optional[str],
    reason: str,
) -> IntegrationBindingRecord:
    if binding.state in {"retired", "expired"}:
        raise BindingValidationError("Binding is already terminal")
    binding.state = "suspended"
    binding.suspended_at = datetime.utcnow()
    clear_adapter_cache(binding.id)
    _audit(db, binding.id, "binding.suspended", actor_id, {"reason": reason[:200]})
    db.commit()
    db.refresh(binding)
    return binding


def expire_due_bindings(db: Session) -> int:
    now = datetime.utcnow()
    rows = db.query(IntegrationBindingRecord).filter(
        IntegrationBindingRecord.expires_at.isnot(None),
        IntegrationBindingRecord.expires_at <= now,
        IntegrationBindingRecord.state.in_(["draft", "validating", "active", "suspended"]),
    ).all()
    for row in rows:
        row.state = "expired"
        clear_adapter_cache(row.id)
        _audit(db, row.id, "binding.expired", None)
    if rows:
        db.commit()
    return len(rows)


def serialize_binding(record: IntegrationBindingRecord) -> dict[str, Any]:
    try:
        workspaces = json.loads(record.workspace_ids or "[]")
    except (TypeError, ValueError):
        workspaces = []
    return {
        "id": record.id,
        "provider": record.provider,
        "environment": record.environment,
        "state": record.state,
        "canonical_account_host": record.canonical_account_host,
        "installation_id": record.installation_id,
        "workspace_ids": workspaces,
        "product_variant": record.product_variant,
        "credential_reference": record.credential_reference,
        "capability_version": record.capability_version,
        "expires_at": record.expires_at,
        "activated_at": record.activated_at,
        "suspended_at": record.suspended_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
