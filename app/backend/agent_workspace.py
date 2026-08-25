"""Assignment and mailbox policy for the Agent workspace.

Freshservice remains authoritative.  This module only translates explicit
identity links and provider group membership into local, read-only work views.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_, false, or_
from sqlalchemy.orm import Session

from .database import (
    ExternalGroupMembershipRecord,
    ExternalGroupRecord,
    ExternalUserRecord,
    TicketRecord,
    UserExternalIdentityLinkRecord,
    UserRecord,
)


@dataclass(frozen=True)
class LinkedIdentity:
    link: UserExternalIdentityLinkRecord
    external_user: ExternalUserRecord


@dataclass(frozen=True)
class AccessibleGroup:
    group: ExternalGroupRecord
    membership_kind: str


def linked_identities(db: Session, user_id: str) -> list[LinkedIdentity]:
    rows = db.query(
        UserExternalIdentityLinkRecord,
        ExternalUserRecord,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id == UserExternalIdentityLinkRecord.external_user_id,
    ).filter(
        UserExternalIdentityLinkRecord.user_id == user_id,
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
    ).order_by(
        UserExternalIdentityLinkRecord.provider,
        UserExternalIdentityLinkRecord.binding_id,
    ).all()
    return [LinkedIdentity(link=link, external_user=external_user) for link, external_user in rows]


def accessible_groups(
    db: Session,
    user_id: str,
    *,
    include_observer: bool = False,
) -> list[AccessibleGroup]:
    identities = linked_identities(db, user_id)
    external_user_ids = [item.external_user.id for item in identities]
    if not external_user_ids:
        return []
    query = db.query(
        ExternalGroupRecord,
        ExternalGroupMembershipRecord.membership_kind,
    ).join(
        ExternalGroupMembershipRecord,
        ExternalGroupMembershipRecord.external_group_id == ExternalGroupRecord.id,
    ).filter(
        ExternalGroupMembershipRecord.external_user_id.in_(external_user_ids),
        ExternalGroupRecord.active.is_(True),
    )
    if not include_observer:
        query = query.filter(
            ExternalGroupMembershipRecord.membership_kind == "member"
        )
    rows = query.order_by(ExternalGroupRecord.name, ExternalGroupRecord.external_id).all()
    seen: set[tuple[str, str]] = set()
    result: list[AccessibleGroup] = []
    for group, membership_kind in rows:
        key = (group.id, membership_kind)
        if key in seen:
            continue
        seen.add(key)
        result.append(AccessibleGroup(group=group, membership_kind=membership_kind))
    return result


def assignment_filter(
    db: Session,
    user: UserRecord,
    *,
    scope: str,
    team_id: Optional[str] = None,
):
    """Return the SQL predicate for a personal or authoritative team inbox."""
    identities = linked_identities(db, user.id)
    if scope == "mine":
        direct_clauses = [TicketRecord.assignee_id == user.id]
        direct_clauses.extend(
            and_(
                TicketRecord.binding_id == identity.link.binding_id,
                TicketRecord.external_source == identity.link.provider,
                TicketRecord.external_assignee_id == identity.external_user.external_id,
            )
            for identity in identities
        )
        return or_(*direct_clauses)

    if scope != "team":
        return false()
    groups = accessible_groups(db, user.id)
    if team_id:
        groups = [item for item in groups if item.group.id == team_id]
    if not groups:
        return false()
    return or_(*[
        and_(
            TicketRecord.binding_id == item.group.binding_id,
            TicketRecord.external_source == item.group.provider,
            TicketRecord.external_group_id == item.group.external_id,
        )
        for item in groups
    ])


def assignment_scope_for_ticket(
    db: Session,
    user: UserRecord,
    ticket: TicketRecord,
) -> tuple[Optional[str], Optional[ExternalGroupRecord]]:
    if ticket.assignee_id == user.id:
        return "mine", None
    identities = linked_identities(db, user.id)
    for identity in identities:
        if (
            ticket.binding_id == identity.link.binding_id
            and (ticket.external_source or "").lower() == identity.link.provider.lower()
            and ticket.external_assignee_id == identity.external_user.external_id
        ):
            return "mine", None
    for item in accessible_groups(db, user.id):
        group = item.group
        if (
            ticket.binding_id == group.binding_id
            and (ticket.external_source or "").lower() == group.provider.lower()
            and ticket.external_group_id == group.external_id
        ):
            return "team", group
    return None, None


def can_work_ticket(db: Session, user: UserRecord, ticket: TicketRecord) -> bool:
    if (user.role or "").lower() in {"admin", "supervisor"}:
        return True
    if (user.role or "").lower() != "agent":
        return False
    scope, _group = assignment_scope_for_ticket(db, user, ticket)
    return scope is not None
