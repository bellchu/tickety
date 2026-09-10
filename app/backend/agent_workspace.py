"""Assignment and mailbox policy for the Agent workspace.

Freshservice remains authoritative.  This module only translates explicit
identity links and provider group membership into local, read-only work views.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_, false, or_, select
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


MAX_LINKED_IDENTITIES = 100
MAX_ACCESSIBLE_GROUPS = 100
# `/tickets` permits at most 500 rows per response; context joins cover the
# whole bounded page without ever walking an unbounded identity/team directory.
MAX_TICKET_ASSIGNMENT_CONTEXT = 500


def _bounded_limit(value: int, maximum: int) -> int:
    return max(1, min(int(value), maximum))


def linked_identities(
    db: Session,
    user_id: str,
    *,
    limit: int = MAX_LINKED_IDENTITIES,
) -> list[LinkedIdentity]:
    """Return an explicitly bounded provider-identity page for display use."""
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
        UserExternalIdentityLinkRecord.id,
    ).limit(_bounded_limit(limit, MAX_LINKED_IDENTITIES)).all()
    return [LinkedIdentity(link=link, external_user=external_user) for link, external_user in rows]


def _accessible_group_query(
    db: Session,
    user_id: str,
    *,
    include_observer: bool = False,
):
    """Join local identity links to provider membership without materializing IDs."""
    query = db.query(
        ExternalGroupRecord,
        ExternalGroupMembershipRecord.membership_kind,
    ).select_from(ExternalGroupRecord).join(
        ExternalGroupMembershipRecord,
        ExternalGroupMembershipRecord.external_group_id == ExternalGroupRecord.id,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id == ExternalGroupMembershipRecord.external_user_id,
    ).join(
        UserExternalIdentityLinkRecord,
        and_(
            UserExternalIdentityLinkRecord.external_user_id == ExternalUserRecord.id,
            UserExternalIdentityLinkRecord.user_id == user_id,
            UserExternalIdentityLinkRecord.binding_id == ExternalUserRecord.binding_id,
            UserExternalIdentityLinkRecord.provider == ExternalUserRecord.provider,
        ),
    ).filter(
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
        ExternalGroupRecord.active.is_(True),
        ExternalGroupRecord.binding_id == ExternalUserRecord.binding_id,
        ExternalGroupRecord.provider == ExternalUserRecord.provider,
    )
    if not include_observer:
        query = query.filter(
            ExternalGroupMembershipRecord.membership_kind == "member"
        )
    return query.distinct().order_by(
        ExternalGroupRecord.name,
        ExternalGroupRecord.external_id,
        ExternalGroupRecord.id,
        ExternalGroupMembershipRecord.membership_kind,
    )


def accessible_groups_page(
    db: Session,
    user_id: str,
    *,
    include_observer: bool = False,
    limit: int = MAX_ACCESSIBLE_GROUPS,
) -> tuple[list[AccessibleGroup], bool]:
    """Return a bounded team page plus an explicit truncation signal."""
    bounded = _bounded_limit(limit, MAX_ACCESSIBLE_GROUPS)
    rows = _accessible_group_query(
        db,
        user_id,
        include_observer=include_observer,
    ).limit(bounded + 1).all()
    return (
        [
            AccessibleGroup(group=group, membership_kind=membership_kind)
            for group, membership_kind in rows[:bounded]
        ],
        len(rows) > bounded,
    )


def accessible_groups(
    db: Session,
    user_id: str,
    *,
    include_observer: bool = False,
    limit: int = MAX_ACCESSIBLE_GROUPS,
) -> list[AccessibleGroup]:
    groups, _truncated = accessible_groups_page(
        db,
        user_id,
        include_observer=include_observer,
        limit=limit,
    )
    return groups


def _linked_identity_ticket_exists(user_id: str):
    return select(1).select_from(
        UserExternalIdentityLinkRecord
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id == UserExternalIdentityLinkRecord.external_user_id,
    ).where(
        UserExternalIdentityLinkRecord.user_id == user_id,
        UserExternalIdentityLinkRecord.binding_id == TicketRecord.binding_id,
        UserExternalIdentityLinkRecord.provider == TicketRecord.external_source,
        ExternalUserRecord.binding_id == TicketRecord.binding_id,
        ExternalUserRecord.provider == TicketRecord.external_source,
        ExternalUserRecord.external_id == TicketRecord.external_assignee_id,
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
    ).correlate(TicketRecord).exists()


def _accessible_group_ticket_exists(user_id: str, team_id: Optional[str] = None):
    query = select(1).select_from(
        ExternalGroupRecord
    ).join(
        ExternalGroupMembershipRecord,
        ExternalGroupMembershipRecord.external_group_id == ExternalGroupRecord.id,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id == ExternalGroupMembershipRecord.external_user_id,
    ).join(
        UserExternalIdentityLinkRecord,
        and_(
            UserExternalIdentityLinkRecord.external_user_id == ExternalUserRecord.id,
            UserExternalIdentityLinkRecord.user_id == user_id,
            UserExternalIdentityLinkRecord.binding_id == ExternalUserRecord.binding_id,
            UserExternalIdentityLinkRecord.provider == ExternalUserRecord.provider,
        ),
    ).where(
        ExternalGroupMembershipRecord.membership_kind == "member",
        ExternalGroupRecord.active.is_(True),
        ExternalUserRecord.active.is_(True),
        ExternalUserRecord.user_type == "agent",
        ExternalGroupRecord.binding_id == ExternalUserRecord.binding_id,
        ExternalGroupRecord.provider == ExternalUserRecord.provider,
        ExternalGroupRecord.binding_id == TicketRecord.binding_id,
        ExternalGroupRecord.provider == TicketRecord.external_source,
        ExternalGroupRecord.external_id == TicketRecord.external_group_id,
    )
    if team_id:
        query = query.where(ExternalGroupRecord.id == team_id)
    return query.correlate(TicketRecord).exists()


def assignment_filter(
    db: Session,
    user: UserRecord,
    *,
    scope: str,
    team_id: Optional[str] = None,
):
    """Return the SQL predicate for a personal or authoritative team inbox."""
    if scope == "mine":
        return or_(
            TicketRecord.assignee_id == user.id,
            _linked_identity_ticket_exists(user.id),
        )

    if scope != "team":
        return false()
    return _accessible_group_ticket_exists(user.id, team_id)


def _bounded_ticket_ids(ticket_ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(ticket_ids))[:MAX_TICKET_ASSIGNMENT_CONTEXT]


def linked_identity_keys_for_tickets(
    db: Session,
    user_id: str,
    ticket_ids: Sequence[str],
) -> set[tuple[str, str, str]]:
    """Resolve direct provider assignments only for a bounded ticket page."""
    bounded_ticket_ids = _bounded_ticket_ids(ticket_ids)
    if not bounded_ticket_ids:
        return set()
    rows = db.query(
        TicketRecord.binding_id,
        TicketRecord.external_source,
        TicketRecord.external_assignee_id,
    ).select_from(TicketRecord).join(
        ExternalUserRecord,
        and_(
            ExternalUserRecord.binding_id == TicketRecord.binding_id,
            ExternalUserRecord.provider == TicketRecord.external_source,
            ExternalUserRecord.external_id == TicketRecord.external_assignee_id,
            ExternalUserRecord.user_type == "agent",
            ExternalUserRecord.active.is_(True),
        ),
    ).join(
        UserExternalIdentityLinkRecord,
        and_(
            UserExternalIdentityLinkRecord.external_user_id == ExternalUserRecord.id,
            UserExternalIdentityLinkRecord.user_id == user_id,
            UserExternalIdentityLinkRecord.binding_id == ExternalUserRecord.binding_id,
            UserExternalIdentityLinkRecord.provider == ExternalUserRecord.provider,
        ),
    ).filter(
        TicketRecord.id.in_(bounded_ticket_ids),
    ).distinct().limit(MAX_TICKET_ASSIGNMENT_CONTEXT).all()
    return {
        (binding_id, provider.lower(), external_assignee_id)
        for binding_id, provider, external_assignee_id in rows
    }


def accessible_groups_for_tickets(
    db: Session,
    user_id: str,
    ticket_ids: Sequence[str],
) -> list[ExternalGroupRecord]:
    """Resolve team labels only for the already bounded ticket response page."""
    bounded_ticket_ids = _bounded_ticket_ids(ticket_ids)
    if not bounded_ticket_ids:
        return []
    return db.query(ExternalGroupRecord).select_from(
        ExternalGroupRecord
    ).join(
        ExternalGroupMembershipRecord,
        ExternalGroupMembershipRecord.external_group_id == ExternalGroupRecord.id,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id == ExternalGroupMembershipRecord.external_user_id,
    ).join(
        UserExternalIdentityLinkRecord,
        and_(
            UserExternalIdentityLinkRecord.external_user_id == ExternalUserRecord.id,
            UserExternalIdentityLinkRecord.user_id == user_id,
            UserExternalIdentityLinkRecord.binding_id == ExternalUserRecord.binding_id,
            UserExternalIdentityLinkRecord.provider == ExternalUserRecord.provider,
        ),
    ).join(
        TicketRecord,
        and_(
            TicketRecord.id.in_(bounded_ticket_ids),
            TicketRecord.binding_id == ExternalGroupRecord.binding_id,
            TicketRecord.external_source == ExternalGroupRecord.provider,
            TicketRecord.external_group_id == ExternalGroupRecord.external_id,
        ),
    ).filter(
        ExternalGroupMembershipRecord.membership_kind == "member",
        ExternalGroupRecord.active.is_(True),
        ExternalUserRecord.active.is_(True),
        ExternalUserRecord.user_type == "agent",
        ExternalGroupRecord.binding_id == ExternalUserRecord.binding_id,
        ExternalGroupRecord.provider == ExternalUserRecord.provider,
    ).distinct().order_by(
        ExternalGroupRecord.name,
        ExternalGroupRecord.external_id,
        ExternalGroupRecord.id,
    ).limit(MAX_TICKET_ASSIGNMENT_CONTEXT).all()


def assignment_scope_for_ticket(
    db: Session,
    user: UserRecord,
    ticket: TicketRecord,
) -> tuple[Optional[str], Optional[ExternalGroupRecord]]:
    if ticket.assignee_id == user.id:
        return "mine", None
    direct = db.query(UserExternalIdentityLinkRecord.id).join(
        ExternalUserRecord,
        ExternalUserRecord.id == UserExternalIdentityLinkRecord.external_user_id,
    ).filter(
        UserExternalIdentityLinkRecord.user_id == user.id,
        UserExternalIdentityLinkRecord.binding_id == ticket.binding_id,
        UserExternalIdentityLinkRecord.provider == ticket.external_source,
        ExternalUserRecord.binding_id == ticket.binding_id,
        ExternalUserRecord.provider == ticket.external_source,
        ExternalUserRecord.external_id == ticket.external_assignee_id,
        ExternalUserRecord.user_type == "agent",
        ExternalUserRecord.active.is_(True),
    ).first()
    if direct:
        return "mine", None
    group = _accessible_group_query(db, user.id).filter(
        ExternalGroupRecord.binding_id == ticket.binding_id,
        ExternalGroupRecord.provider == ticket.external_source,
        ExternalGroupRecord.external_id == ticket.external_group_id,
    ).first()
    if group:
        return "team", group[0]
    return None, None


def can_work_ticket(db: Session, user: UserRecord, ticket: TicketRecord) -> bool:
    if (user.role or "").lower() in {"admin", "supervisor"}:
        return True
    if (user.role or "").lower() != "agent":
        return False
    scope, _group = assignment_scope_for_ticket(db, user, ticket)
    return scope is not None
