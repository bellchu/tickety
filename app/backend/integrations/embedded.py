"""Authentication boundary for the Freshworks embedded application.

The browser never receives the installation secret. Freshworks Request Method
injects it into bootstrap/redeem calls, which exchange a single-use code for a
short-lived, ticket-scoped bearer token.
"""

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..database import (
    IntegrationAuditRecord,
    IntegrationBindingRecord,
    IntegrationBootstrapRecord,
    IntegrationSessionRecord,
    ExternalUserRecord,
    TicketRecord,
)
from .bindings import normalize_freshservice_host


BOOTSTRAP_TTL_SECONDS = 90
SESSION_TTL_SECONDS = 600


class EmbeddedAuthError(ValueError):
    pass


@dataclass(frozen=True)
class EmbeddedPrincipal:
    session: IntegrationSessionRecord
    binding: IntegrationBindingRecord
    external_user: ExternalUserRecord


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _configured_secret() -> str:
    secret = os.getenv("FRESHWORKS_APP_BOOTSTRAP_SECRET", "")
    if len(secret) < 32 or secret.lower() in {"change-me", "replace-me"}:
        raise EmbeddedAuthError("Freshworks embedded authentication is unavailable")
    return secret


def verify_installation_secret(supplied: Optional[str]) -> None:
    expected = _configured_secret()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise EmbeddedAuthError("Freshworks embedded authentication failed")


def _workspace_ids(binding: IntegrationBindingRecord) -> set[str]:
    try:
        values = json.loads(binding.workspace_ids or "[]")
    except (TypeError, ValueError):
        return set()
    return {str(value) for value in values} if isinstance(values, list) else set()


def _audit(db: Session, binding_id: str, action: str, actor_id: Optional[str]) -> None:
    db.add(IntegrationAuditRecord(
        binding_id=binding_id,
        action=action,
        actor_id=actor_id,
        details="{}",
    ))


def issue_bootstrap_code(
    db: Session,
    *,
    binding_id: str,
    account_host: str,
    external_user_id: str,
    workspace_id: Optional[str],
    external_ticket_id: Optional[str],
    ticket_updated_at: Optional[datetime],
    audience: str,
) -> tuple[str, datetime]:
    now = datetime.utcnow()
    binding = db.query(IntegrationBindingRecord).filter(
        IntegrationBindingRecord.id == binding_id,
        IntegrationBindingRecord.provider == "freshservice",
        IntegrationBindingRecord.state == "active",
    ).first()
    if not binding or (binding.expires_at and binding.expires_at <= now):
        raise EmbeddedAuthError("Freshworks binding is unavailable")
    if normalize_freshservice_host(account_host) != binding.canonical_account_host:
        raise EmbeddedAuthError("Freshworks account does not match the binding")

    normalized_workspace = str(workspace_id).strip() if workspace_id is not None else None
    allowed_workspaces = _workspace_ids(binding)
    if allowed_workspaces and normalized_workspace not in allowed_workspaces:
        raise EmbeddedAuthError("Freshworks workspace does not match the binding")
    if audience == "ticket_sidebar" and not external_ticket_id:
        raise EmbeddedAuthError("Ticket sidebar bootstrap requires a ticket")

    external_user = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.binding_id == binding.id,
        ExternalUserRecord.provider == "freshservice",
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.external_id == external_user_id,
        ExternalUserRecord.active.is_(True),
    ).first()
    if not external_user:
        raise EmbeddedAuthError("Freshworks agent is not present in the external directory")

    if external_ticket_id:
        ticket = db.query(TicketRecord).filter(
            TicketRecord.binding_id == binding.id,
            TicketRecord.external_source == "freshservice",
            TicketRecord.external_id == external_ticket_id,
        ).first()
        if not ticket:
            raise EmbeddedAuthError("Freshworks ticket is not synchronized to this binding")
        if (
            ticket.external_workspace_id
            and normalized_workspace
            and ticket.external_workspace_id != normalized_workspace
        ):
            raise EmbeddedAuthError("Ticket workspace does not match the binding context")

    code = secrets.token_urlsafe(32)
    expires_at = now + timedelta(seconds=BOOTSTRAP_TTL_SECONDS)
    context = {
        "external_user_id": external_user_id,
        "workspace_id": normalized_workspace,
        "external_ticket_id": external_ticket_id,
        "ticket_updated_at": ticket_updated_at.isoformat() if ticket_updated_at else None,
        "audience": audience,
    }
    db.add(IntegrationBootstrapRecord(
        code_hash=_digest(code),
        binding_id=binding.id,
        external_user_id=external_user_id,
        workspace_id=normalized_workspace,
        audience=audience,
        context_json=json.dumps(context, sort_keys=True, separators=(",", ":")),
        expires_at=expires_at,
    ))
    _audit(db, binding.id, "embedded.bootstrap_issued", None)
    db.query(IntegrationBootstrapRecord).filter(
        IntegrationBootstrapRecord.expires_at < now - timedelta(minutes=10)
    ).delete(synchronize_session=False)
    db.query(IntegrationSessionRecord).filter(
        IntegrationSessionRecord.expires_at < now - timedelta(hours=1)
    ).delete(synchronize_session=False)
    db.commit()
    return code, expires_at


def redeem_bootstrap_code(
    db: Session, *, binding_id: str, code: str
) -> tuple[str, IntegrationSessionRecord]:
    now = datetime.utcnow()
    bootstrap = db.query(IntegrationBootstrapRecord).filter(
        IntegrationBootstrapRecord.code_hash == _digest(code),
        IntegrationBootstrapRecord.binding_id == binding_id,
    ).with_for_update().first()
    if not bootstrap or bootstrap.redeemed_at or bootstrap.expires_at <= now:
        raise EmbeddedAuthError("Bootstrap code is invalid or expired")
    binding = db.query(IntegrationBindingRecord).filter(
        IntegrationBindingRecord.id == binding_id,
        IntegrationBindingRecord.state == "active",
    ).first()
    if not binding or (binding.expires_at and binding.expires_at <= now):
        raise EmbeddedAuthError("Freshworks binding is unavailable")
    try:
        context = json.loads(bootstrap.context_json or "{}")
    except (TypeError, ValueError) as exc:
        raise EmbeddedAuthError("Bootstrap context is invalid") from exc
    external_user = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.binding_id == binding.id,
        ExternalUserRecord.provider == "freshservice",
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.external_id == str(context.get("external_user_id") or ""),
        ExternalUserRecord.active.is_(True),
    ).first()
    if not external_user:
        raise EmbeddedAuthError("Freshworks agent is unavailable")

    token = secrets.token_urlsafe(32)
    session = IntegrationSessionRecord(
        token_hash=_digest(token),
        binding_id=binding.id,
        external_user_id=str(context.get("external_user_id") or ""),
        workspace_id=context.get("workspace_id"),
        external_ticket_id=context.get("external_ticket_id"),
        audience=str(context.get("audience") or "freshworks"),
        expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
    )
    bootstrap.redeemed_at = now
    db.add(session)
    _audit(db, binding.id, "embedded.session_issued", None)
    db.commit()
    db.refresh(session)
    return token, session


def authenticate_session(db: Session, authorization: Optional[str]) -> EmbeddedPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise EmbeddedAuthError("Embedded session is required")
    token = authorization[7:].strip()
    if not token or " " in token:
        raise EmbeddedAuthError("Embedded session is invalid")
    now = datetime.utcnow()
    session = db.query(IntegrationSessionRecord).filter(
        IntegrationSessionRecord.token_hash == _digest(token),
        IntegrationSessionRecord.revoked_at.is_(None),
        IntegrationSessionRecord.expires_at > now,
    ).first()
    if not session:
        raise EmbeddedAuthError("Embedded session is invalid or expired")
    binding = db.query(IntegrationBindingRecord).filter(
        IntegrationBindingRecord.id == session.binding_id,
        IntegrationBindingRecord.state == "active",
    ).first()
    external_user = db.query(ExternalUserRecord).filter(
        ExternalUserRecord.binding_id == session.binding_id,
        ExternalUserRecord.provider == "freshservice",
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.external_id == session.external_user_id,
        ExternalUserRecord.active.is_(True),
    ).first()
    if not binding or not external_user or (binding.expires_at and binding.expires_at <= now):
        raise EmbeddedAuthError("Embedded session context is unavailable")
    session.last_seen_at = now
    db.commit()
    return EmbeddedPrincipal(
        session=session, binding=binding, external_user=external_user
    )


def require_ticket_scope(principal: EmbeddedPrincipal, external_ticket_id: str) -> None:
    if (
        principal.session.audience != "ticket_sidebar"
        or principal.session.external_ticket_id != external_ticket_id
    ):
        raise EmbeddedAuthError("Embedded session is not authorized for this ticket")
