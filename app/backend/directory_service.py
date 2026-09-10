"""Canonical local/remote people without crossing the authentication boundary."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any, Iterable, Optional
import uuid

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai_contracts import AI_RESOLVER_TEAMS
from .database import (
    AgentResolverTeamMappingAuditRecord,
    AgentResolverTeamMappingRecord,
    DirectoryIdentityLinkAuditRecord,
    DirectoryPersonExternalIdentityRecord,
    DirectoryPersonLocalAccountRecord,
    DirectoryPersonRecord,
    DirectoryPersonResolverTeamAuditRecord,
    DirectoryPersonResolverTeamMappingRecord,
    DirectorySyncRunRecord,
    DirectorySyncStateRecord,
    ExternalUserRecord,
    SessionLocal,
    UserExternalIdentityAuditRecord,
    UserExternalIdentityLinkRecord,
    UserRecord,
    normalize_user_email,
)
from .integrations.sync import (
    async_sync_external_users,
    reconcile_embedded_agent_identities,
)
from .portable_keys import portable_ascii_lower_expression
from . import settings as settings_module


class DirectoryError(RuntimeError):
    pass


class DirectoryNotFound(DirectoryError):
    pass


class DirectoryConflict(DirectoryError):
    pass


class DirectoryIneligible(DirectoryError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _new_person(db: Session, *, now: Optional[datetime] = None) -> DirectoryPersonRecord:
    now = now or datetime.utcnow()
    person = DirectoryPersonRecord(
        id=str(uuid.uuid4()),
        state="active",
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(person)
    db.flush()
    return person


def ensure_local_person(
    db: Session, user_id: str
) -> DirectoryPersonLocalAccountRecord:
    attachment = db.query(DirectoryPersonLocalAccountRecord).filter(
        DirectoryPersonLocalAccountRecord.user_id == user_id
    ).first()
    if attachment is not None:
        return attachment
    if db.get(UserRecord, user_id) is None:
        raise DirectoryNotFound("Local user not found")
    now = datetime.utcnow()
    person = _new_person(db, now=now)
    attachment = DirectoryPersonLocalAccountRecord(
        person_id=person.id,
        user_id=user_id,
        created_at=now,
    )
    db.add(attachment)
    db.flush()
    return attachment


def ensure_external_identity_person(
    db: Session, external_user_id: str
) -> DirectoryPersonExternalIdentityRecord:
    attachment = db.query(DirectoryPersonExternalIdentityRecord).filter(
        DirectoryPersonExternalIdentityRecord.external_user_id == external_user_id
    ).first()
    if attachment is not None:
        return attachment
    external = db.get(ExternalUserRecord, external_user_id)
    if external is None:
        raise DirectoryNotFound("External directory identity not found")
    now = datetime.utcnow()
    legacy = db.query(UserExternalIdentityLinkRecord).filter(
        UserExternalIdentityLinkRecord.external_user_id == external_user_id
    ).first()
    if legacy is not None:
        local = ensure_local_person(db, legacy.user_id)
        person_id = local.person_id
        method = "backfill_manual"
        actor_id = legacy.created_by
        created_at = legacy.created_at or now
        updated_at = legacy.updated_at or created_at
    else:
        person_id = _new_person(db, now=now).id
        method = "source"
        actor_id = None
        created_at = now
        updated_at = now
    attachment = DirectoryPersonExternalIdentityRecord(
        person_id=person_id,
        external_user_id=external_user_id,
        link_method=method,
        link_state="active",
        actor_id=actor_id,
        created_at=created_at,
        updated_at=updated_at,
    )
    db.add(attachment)
    db.flush()
    return attachment


def ensure_directory_projection(db: Session) -> dict[str, int]:
    """Create missing person attachments without guessing identity links."""
    counts = {"local_people_created": 0, "remote_people_created": 0}
    now = datetime.utcnow()
    local_user_ids = {
        row[0] for row in db.query(DirectoryPersonLocalAccountRecord.user_id).all()
    }
    for user in db.query(UserRecord).order_by(UserRecord.id).all():
        if user.id in local_user_ids:
            continue
        person = _new_person(db, now=now)
        db.add(DirectoryPersonLocalAccountRecord(
            person_id=person.id,
            user_id=user.id,
            created_at=now,
        ))
        local_user_ids.add(user.id)
        counts["local_people_created"] += 1
    db.flush()

    local_people = dict(db.query(
        DirectoryPersonLocalAccountRecord.user_id,
        DirectoryPersonLocalAccountRecord.person_id,
    ).all())
    legacy_links = {
        row.external_user_id: row
        for row in db.query(UserExternalIdentityLinkRecord).all()
    }
    attached = {
        row[0]
        for row in db.query(
            DirectoryPersonExternalIdentityRecord.external_user_id
        ).all()
    }
    for external in db.query(ExternalUserRecord).order_by(
        ExternalUserRecord.binding_id,
        ExternalUserRecord.provider,
        ExternalUserRecord.user_type,
        ExternalUserRecord.external_id,
    ).all():
        if external.id in attached:
            continue
        legacy = legacy_links.get(external.id)
        target_person_id = local_people.get(legacy.user_id) if legacy else None
        if target_person_id:
            person_id = target_person_id
            method = "backfill_manual"
            actor_id = legacy.created_by
            created_at = legacy.created_at or now
            updated_at = legacy.updated_at or created_at
        else:
            person_id = _new_person(db, now=now).id
            method = "source"
            actor_id = None
            created_at = now
            updated_at = now
            counts["remote_people_created"] += 1
        db.add(DirectoryPersonExternalIdentityRecord(
            person_id=person_id,
            external_user_id=external.id,
            link_method=method,
            link_state="active",
            actor_id=actor_id,
            created_at=created_at,
            updated_at=updated_at,
        ))
        attached.add(external.id)
    db.flush()
    return counts


def _person_for_user(
    db: Session, user_id: str, *, lock: bool = False
) -> tuple[DirectoryPersonRecord, DirectoryPersonLocalAccountRecord]:
    query = db.query(
        DirectoryPersonRecord,
        DirectoryPersonLocalAccountRecord,
    ).join(
        DirectoryPersonLocalAccountRecord,
        DirectoryPersonLocalAccountRecord.person_id == DirectoryPersonRecord.id,
    ).filter(
        DirectoryPersonLocalAccountRecord.user_id == user_id,
        DirectoryPersonRecord.state == "active",
    )
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise DirectoryNotFound("Local directory person not found")
    return row


def _external_attachment(
    db: Session, external_user_id: str, *, lock: bool = False
) -> tuple[
    DirectoryPersonExternalIdentityRecord,
    ExternalUserRecord,
    DirectoryPersonRecord,
]:
    query = db.query(
        DirectoryPersonExternalIdentityRecord,
        ExternalUserRecord,
        DirectoryPersonRecord,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id
        == DirectoryPersonExternalIdentityRecord.external_user_id,
    ).join(
        DirectoryPersonRecord,
        DirectoryPersonRecord.id == DirectoryPersonExternalIdentityRecord.person_id,
    ).filter(
        DirectoryPersonExternalIdentityRecord.external_user_id == external_user_id,
    )
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise DirectoryNotFound("External directory identity not found")
    return row


def _person_payload(db: Session, person_id: str) -> dict[str, Any]:
    person = db.get(DirectoryPersonRecord, person_id)
    if person is None or person.state != "active":
        raise DirectoryNotFound("Directory person not found")
    local_row = db.query(
        DirectoryPersonLocalAccountRecord,
        UserRecord,
    ).join(
        UserRecord,
        UserRecord.id == DirectoryPersonLocalAccountRecord.user_id,
    ).filter(
        DirectoryPersonLocalAccountRecord.person_id == person_id,
    ).first()
    external_rows = db.query(
        DirectoryPersonExternalIdentityRecord,
        ExternalUserRecord,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id
        == DirectoryPersonExternalIdentityRecord.external_user_id,
    ).filter(
        DirectoryPersonExternalIdentityRecord.person_id == person_id,
    ).order_by(
        ExternalUserRecord.user_type,
        portable_ascii_lower_expression(ExternalUserRecord.name),
        ExternalUserRecord.external_id,
    ).all()
    memberships = db.query(DirectoryPersonResolverTeamMappingRecord).filter(
        DirectoryPersonResolverTeamMappingRecord.person_id == person_id,
    ).order_by(
        DirectoryPersonResolverTeamMappingRecord.resolver_group
    ).all()
    local_user = local_row[1] if local_row else None
    preferred_external = next(
        (external for _attachment, external in external_rows if external.user_type == "agent"),
        external_rows[0][1] if external_rows else None,
    )
    display_source = local_user or preferred_external
    local_active = bool(local_user and local_user.is_active)
    remote_active = any(bool(external.active) for _attachment, external in external_rows)
    source_types: list[str] = []
    if local_user:
        source_types.append("local")
    if any(external.user_type == "agent" for _attachment, external in external_rows):
        source_types.append("freshservice_agent")
    if any(external.user_type == "requester" for _attachment, external in external_rows):
        source_types.append("freshservice_requester")
    updated_at = max(
        [person.updated_at]
        + [row.updated_at for row in memberships]
        + [attachment.updated_at for attachment, _external in external_rows]
    )
    fetched_values = [
        external.fetched_at for _attachment, external in external_rows
        if external.fetched_at is not None
    ]
    return {
        "id": person.id,
        "version": person.version,
        "name": getattr(display_source, "name", None) or "Unnamed person",
        "email": getattr(display_source, "email", None),
        "title": getattr(display_source, "title", None),
        "user_id": local_user.id if local_user else None,
        "role": (local_user.role or "agent").lower() if local_user else None,
        "local_active": local_active,
        "remote_active": remote_active,
        "effective_active": local_active or remote_active,
        "linked": bool(local_user and external_rows),
        "source_types": source_types,
        "resolver_groups": [row.resolver_group for row in memberships],
        "identities": [
            {
                "attachment_id": attachment.id,
                "external_user_id": external.id,
                "binding_id": external.binding_id,
                "provider": external.provider,
                "external_id": external.external_id,
                "user_type": external.user_type,
                "name": external.name,
                "email": external.email,
                "title": external.title,
                "active": bool(external.active),
                "link_method": attachment.link_method,
                "link_state": attachment.link_state,
                "review_reason": attachment.review_reason,
                "fetched_at": external.fetched_at,
            }
            for attachment, external in external_rows
        ],
        "updated_at": updated_at,
        "last_fetched_at": max(fetched_values) if fetched_values else None,
    }


def list_directory_people(
    db: Session,
    *,
    search: str = "",
    active: Optional[bool] = True,
    source_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    local_exists = exists().where(
        DirectoryPersonLocalAccountRecord.person_id == DirectoryPersonRecord.id
    )
    agent_exists = exists().where(
        DirectoryPersonExternalIdentityRecord.person_id == DirectoryPersonRecord.id,
        DirectoryPersonExternalIdentityRecord.external_user_id == ExternalUserRecord.id,
        ExternalUserRecord.user_type == "agent",
    )
    requester_exists = exists().where(
        DirectoryPersonExternalIdentityRecord.person_id == DirectoryPersonRecord.id,
        DirectoryPersonExternalIdentityRecord.external_user_id == ExternalUserRecord.id,
        ExternalUserRecord.user_type == "requester",
    )
    local_active_exists = exists().where(
        DirectoryPersonLocalAccountRecord.person_id == DirectoryPersonRecord.id,
        DirectoryPersonLocalAccountRecord.user_id == UserRecord.id,
        UserRecord.is_active.is_(True),
    )
    remote_active_exists = exists().where(
        DirectoryPersonExternalIdentityRecord.person_id == DirectoryPersonRecord.id,
        DirectoryPersonExternalIdentityRecord.external_user_id == ExternalUserRecord.id,
        ExternalUserRecord.active.is_(True),
    )
    query = db.query(DirectoryPersonRecord.id).filter(
        DirectoryPersonRecord.state == "active"
    )
    if active is True:
        query = query.filter(or_(local_active_exists, remote_active_exists))
    elif active is False:
        query = query.filter(~local_active_exists, ~remote_active_exists)
    if source_type == "local":
        query = query.filter(local_exists)
    elif source_type == "agent":
        query = query.filter(agent_exists)
    elif source_type == "requester":
        query = query.filter(requester_exists)
    elif source_type == "remote":
        query = query.filter(or_(agent_exists, requester_exists))
    normalized_search = " ".join(search.split()).lower()
    if normalized_search:
        escaped = (
            normalized_search.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        local_match = exists().where(
            DirectoryPersonLocalAccountRecord.person_id == DirectoryPersonRecord.id,
            DirectoryPersonLocalAccountRecord.user_id == UserRecord.id,
            or_(
                portable_ascii_lower_expression(UserRecord.name).like(pattern, escape="\\"),
                portable_ascii_lower_expression(UserRecord.email).like(pattern, escape="\\"),
                portable_ascii_lower_expression(UserRecord.title).like(pattern, escape="\\"),
            ),
        )
        external_match = exists().where(
            DirectoryPersonExternalIdentityRecord.person_id == DirectoryPersonRecord.id,
            DirectoryPersonExternalIdentityRecord.external_user_id == ExternalUserRecord.id,
            or_(
                portable_ascii_lower_expression(ExternalUserRecord.name).like(pattern, escape="\\"),
                portable_ascii_lower_expression(ExternalUserRecord.email).like(pattern, escape="\\"),
                portable_ascii_lower_expression(ExternalUserRecord.title).like(pattern, escape="\\"),
                portable_ascii_lower_expression(ExternalUserRecord.external_id).like(pattern, escape="\\"),
            ),
        )
        query = query.filter(or_(local_match, external_match))

    local_name = select(UserRecord.name).join(
        DirectoryPersonLocalAccountRecord,
        DirectoryPersonLocalAccountRecord.user_id == UserRecord.id,
    ).where(
        DirectoryPersonLocalAccountRecord.person_id == DirectoryPersonRecord.id
    ).limit(1).scalar_subquery()
    external_name = select(func.min(ExternalUserRecord.name)).join(
        DirectoryPersonExternalIdentityRecord,
        DirectoryPersonExternalIdentityRecord.external_user_id == ExternalUserRecord.id,
    ).where(
        DirectoryPersonExternalIdentityRecord.person_id == DirectoryPersonRecord.id
    ).scalar_subquery()
    sort_name = portable_ascii_lower_expression(
        func.coalesce(local_name, external_name, DirectoryPersonRecord.id)
    )
    total = query.order_by(None).count()
    ids = [row[0] for row in query.order_by(
        sort_name.asc(), DirectoryPersonRecord.id.asc()
    ).offset(offset).limit(limit).all()]
    return {
        "items": [_person_payload(db, person_id) for person_id in ids],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(ids) < total,
    }


def get_directory_person(db: Session, person_id: str) -> dict[str, Any]:
    return _person_payload(db, person_id)


def get_directory_person_for_user(db: Session, user_id: str) -> dict[str, Any]:
    ensure_local_person(db, user_id)
    person, _attachment = _person_for_user(db, user_id)
    return _person_payload(db, person.id)


def _current_groups(db: Session, person_id: str) -> list[str]:
    return [
        row[0] for row in db.query(
            DirectoryPersonResolverTeamMappingRecord.resolver_group
        ).filter(
            DirectoryPersonResolverTeamMappingRecord.person_id == person_id
        ).order_by(
            DirectoryPersonResolverTeamMappingRecord.resolver_group
        ).all()
    ]


def _local_user_for_person(db: Session, person_id: str) -> Optional[UserRecord]:
    return db.query(UserRecord).join(
        DirectoryPersonLocalAccountRecord,
        DirectoryPersonLocalAccountRecord.user_id == UserRecord.id,
    ).filter(
        DirectoryPersonLocalAccountRecord.person_id == person_id
    ).first()


def _mirror_legacy_memberships(
    db: Session,
    *,
    local_user: UserRecord,
    requested: Iterable[str],
    actor_id: Optional[str],
) -> None:
    requested_groups = sorted(set(requested))
    requested_set = set(requested_groups)
    legacy_rows = db.query(AgentResolverTeamMappingRecord).filter(
        AgentResolverTeamMappingRecord.user_id == local_user.id
    ).all()
    legacy_current = sorted(row.resolver_group for row in legacy_rows)
    for row in legacy_rows:
        if row.resolver_group not in requested_set:
            db.delete(row)
    legacy_set = set(legacy_current)
    for group in requested_groups:
        if group not in legacy_set:
            db.add(AgentResolverTeamMappingRecord(
                user_id=local_user.id,
                resolver_group=group,
                created_by=actor_id,
            ))
    if legacy_current != requested_groups:
        db.add(AgentResolverTeamMappingAuditRecord(
            user_id=local_user.id,
            actor_id=actor_id,
            previous_groups=_canonical_json(legacy_current),
            new_groups=_canonical_json(requested_groups),
        ))


def _assert_membership_eligible(db: Session, person_id: str) -> None:
    local = _local_user_for_person(db, person_id)
    if local and local.is_active and (local.role or "").lower() in {
        "admin", "supervisor", "agent"
    }:
        return
    remote_types = {
        row[0] for row in db.query(ExternalUserRecord.user_type).join(
            DirectoryPersonExternalIdentityRecord,
            DirectoryPersonExternalIdentityRecord.external_user_id == ExternalUserRecord.id,
        ).filter(
            DirectoryPersonExternalIdentityRecord.person_id == person_id,
            ExternalUserRecord.active.is_(True),
        ).all()
    }
    if "agent" in remote_types and settings_module.get_bool(
        "REMOTE_AGENT_TEAM_ELIGIBLE"
    ):
        return
    if "requester" in remote_types and settings_module.get_bool(
        "REMOTE_REQUESTER_TEAM_ELIGIBLE"
    ):
        return
    raise DirectoryIneligible("This person is not currently eligible for team membership")


def replace_person_memberships(
    db: Session,
    *,
    person_id: str,
    resolver_groups: Iterable[str],
    actor_id: str,
    expected_version: Optional[int] = None,
    expected_groups: Optional[Iterable[str]] = None,
    mirror_legacy: bool = True,
) -> dict[str, Any]:
    requested = sorted(set(resolver_groups))
    if any(group not in AI_RESOLVER_TEAMS for group in requested):
        raise DirectoryIneligible("Resolver groups must use the closed Tickety catalog")
    person = db.query(DirectoryPersonRecord).filter(
        DirectoryPersonRecord.id == person_id,
        DirectoryPersonRecord.state == "active",
    ).with_for_update().first()
    if person is None:
        raise DirectoryNotFound("Directory person not found")
    if expected_version is not None and person.version != expected_version:
        raise DirectoryConflict("Directory person changed; refresh and retry")
    _assert_membership_eligible(db, person_id)
    current = _current_groups(db, person_id)
    if expected_groups is not None and current != sorted(set(expected_groups)):
        raise DirectoryConflict("Directory membership changed; refresh and retry")
    if current == requested:
        local_user = _local_user_for_person(db, person_id)
        if mirror_legacy and local_user is not None:
            _mirror_legacy_memberships(
                db,
                local_user=local_user,
                requested=requested,
                actor_id=actor_id,
            )
            db.flush()
        return _person_payload(db, person_id)

    rows = db.query(DirectoryPersonResolverTeamMappingRecord).filter(
        DirectoryPersonResolverTeamMappingRecord.person_id == person_id
    ).all()
    current_by_group = {row.resolver_group: row for row in rows}
    requested_set = set(requested)
    for group, row in current_by_group.items():
        if group not in requested_set:
            db.delete(row)
    for group in requested:
        if group not in current_by_group:
            db.add(DirectoryPersonResolverTeamMappingRecord(
                person_id=person_id,
                resolver_group=group,
                version=1,
                created_by=actor_id,
            ))
    person.version += 1
    person.updated_at = datetime.utcnow()
    db.add(DirectoryPersonResolverTeamAuditRecord(
        person_id=person_id,
        actor_id=actor_id,
        action="replaced",
        previous_groups=_canonical_json(current),
        new_groups=_canonical_json(requested),
        details=_canonical_json({"source": "directory_service"}),
    ))

    local_user = _local_user_for_person(db, person_id)
    if mirror_legacy and local_user is not None:
        _mirror_legacy_memberships(
            db,
            local_user=local_user,
            requested=requested,
            actor_id=actor_id,
        )
    db.flush()
    return _person_payload(db, person_id)


def _move_source_memberships(
    db: Session,
    *,
    source_person_id: str,
    target_person_id: str,
    actor_id: Optional[str],
) -> None:
    source_groups = _current_groups(db, source_person_id)
    target_groups = _current_groups(db, target_person_id)
    target_set = set(target_groups)
    for group in source_groups:
        if group not in target_set:
            db.add(DirectoryPersonResolverTeamMappingRecord(
                person_id=target_person_id,
                resolver_group=group,
                version=1,
                created_by=actor_id,
            ))
    db.query(DirectoryPersonResolverTeamMappingRecord).filter(
        DirectoryPersonResolverTeamMappingRecord.person_id == source_person_id
    ).delete(synchronize_session=False)
    merged = sorted(target_set | set(source_groups))
    if source_groups:
        details = _canonical_json({"merged_from_person_id": source_person_id})
        db.add(DirectoryPersonResolverTeamAuditRecord(
            person_id=target_person_id,
            actor_id=actor_id,
            action="merged",
            previous_groups=_canonical_json(target_groups),
            new_groups=_canonical_json(merged),
            details=details,
        ))
        db.add(DirectoryPersonResolverTeamAuditRecord(
            person_id=source_person_id,
            actor_id=actor_id,
            action="merged_into",
            previous_groups=_canonical_json(source_groups),
            new_groups="[]",
            details=_canonical_json({"target_person_id": target_person_id}),
        ))


def _unlink_attachment_topology(
    db: Session,
    *,
    attachment: DirectoryPersonExternalIdentityRecord,
    actor_id: Optional[str],
    move_groups: Iterable[str] = (),
) -> DirectoryPersonRecord:
    source_person = db.query(DirectoryPersonRecord).filter(
        DirectoryPersonRecord.id == attachment.person_id
    ).with_for_update().one()
    has_local = db.query(DirectoryPersonLocalAccountRecord).filter(
        DirectoryPersonLocalAccountRecord.person_id == source_person.id
    ).first() is not None
    attachment_count = db.query(DirectoryPersonExternalIdentityRecord).filter(
        DirectoryPersonExternalIdentityRecord.person_id == source_person.id
    ).count()
    if not has_local and attachment_count <= 1:
        raise DirectoryConflict("External identity is already remote-only")
    current_groups = _current_groups(db, source_person.id)
    move_set = set(move_groups)
    if not move_set.issubset(current_groups):
        raise DirectoryConflict("Only current memberships can move during unlink")
    detached_person = _new_person(db)
    attachment.person_id = detached_person.id
    attachment.link_method = "source"
    attachment.link_state = "active"
    attachment.review_reason = None
    attachment.actor_id = None
    attachment.updated_at = datetime.utcnow()
    if move_set:
        _assert_membership_eligible(db, detached_person.id)
        rows = db.query(DirectoryPersonResolverTeamMappingRecord).filter(
            DirectoryPersonResolverTeamMappingRecord.person_id == source_person.id,
            DirectoryPersonResolverTeamMappingRecord.resolver_group.in_(move_set),
        ).all()
        for row in rows:
            db.delete(row)
            db.add(DirectoryPersonResolverTeamMappingRecord(
                person_id=detached_person.id,
                resolver_group=row.resolver_group,
                version=1,
                created_by=actor_id,
            ))
    source_person.version += 1
    source_person.updated_at = datetime.utcnow()
    db.add(DirectoryIdentityLinkAuditRecord(
        person_id=detached_person.id,
        previous_person_id=source_person.id,
        external_user_id=attachment.external_user_id,
        action="unlinked",
        actor_id=actor_id,
        details=_canonical_json({"moved_groups": sorted(move_set)}),
    ))
    if move_set:
        remaining = sorted(set(current_groups) - move_set)
        db.add(DirectoryPersonResolverTeamAuditRecord(
            person_id=source_person.id,
            actor_id=actor_id,
            action="split",
            previous_groups=_canonical_json(current_groups),
            new_groups=_canonical_json(remaining),
            details=_canonical_json({"detached_person_id": detached_person.id}),
        ))
        db.add(DirectoryPersonResolverTeamAuditRecord(
            person_id=detached_person.id,
            actor_id=actor_id,
            action="split_from",
            previous_groups="[]",
            new_groups=_canonical_json(sorted(move_set)),
            details=_canonical_json({"source_person_id": source_person.id}),
        ))
    if has_local:
        local_user = _local_user_for_person(db, source_person.id)
        if local_user is not None:
            _mirror_legacy_memberships(
                db,
                local_user=local_user,
                requested=sorted(set(current_groups) - move_set),
                actor_id=actor_id,
            )
    return detached_person


def _upsert_legacy_agent_link(
    db: Session,
    *,
    user: UserRecord,
    external: ExternalUserRecord,
    actor_id: Optional[str],
) -> UserExternalIdentityLinkRecord:
    claimed = db.query(UserExternalIdentityLinkRecord).filter(
        UserExternalIdentityLinkRecord.external_user_id == external.id,
        UserExternalIdentityLinkRecord.user_id != user.id,
    ).first()
    if claimed:
        raise DirectoryConflict("That external agent is already linked to another user")
    link = db.query(UserExternalIdentityLinkRecord).filter(
        UserExternalIdentityLinkRecord.user_id == user.id,
        UserExternalIdentityLinkRecord.binding_id == external.binding_id,
        UserExternalIdentityLinkRecord.provider == external.provider,
    ).first()
    now = datetime.utcnow()
    previous_external_user_id = link.external_user_id if link else None
    if link and link.external_user_id != external.id:
        previous_attachment = db.query(
            DirectoryPersonExternalIdentityRecord
        ).filter(
            DirectoryPersonExternalIdentityRecord.external_user_id
            == link.external_user_id
        ).first()
        if previous_attachment and previous_attachment.person_id == _person_for_user(
            db, user.id
        )[0].id:
            _unlink_attachment_topology(
                db,
                attachment=previous_attachment,
                actor_id=actor_id,
            )
    if link is None:
        link = UserExternalIdentityLinkRecord(
            user_id=user.id,
            external_user_id=external.id,
            binding_id=external.binding_id,
            provider=external.provider,
            created_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(link)
    else:
        link.external_user_id = external.id
        link.updated_at = now
    db.add(UserExternalIdentityAuditRecord(
        user_id=user.id,
        external_user_id=external.id,
        binding_id=external.binding_id,
        provider=external.provider,
        action="linked" if previous_external_user_id is None else "relinked",
        actor_id=actor_id,
        details=_canonical_json({
            "previous_external_user_id": previous_external_user_id,
            "external_user_id": external.id,
        }),
        created_at=now,
    ))
    return link


def link_external_identity(
    db: Session,
    *,
    user_id: str,
    external_user_id: str,
    actor_id: Optional[str],
    method: str = "manual",
    expected_person_version: Optional[int] = None,
    mirror_legacy_agent: bool = True,
) -> dict[str, Any]:
    if method not in {"backfill_manual", "manual", "auto_exact_email"}:
        raise ValueError("Unsupported directory link method")
    ensure_local_person(db, user_id)
    ensure_external_identity_person(db, external_user_id)
    target_person, _local_attachment = _person_for_user(db, user_id, lock=True)
    user = db.get(UserRecord, user_id)
    if user is None or not user.is_active or (user.role or "").lower() not in {
        "admin", "supervisor", "agent"
    }:
        raise DirectoryIneligible("Only active operational users can receive identities")
    if expected_person_version is not None and target_person.version != expected_person_version:
        raise DirectoryConflict("Directory person changed; refresh and retry")
    attachment, external, source_person = _external_attachment(
        db, external_user_id, lock=True
    )
    if not external.active:
        raise DirectoryIneligible("Only active remote identities can be linked")
    previous_person_id = source_person.id
    if source_person.id != target_person.id:
        source_local = db.query(DirectoryPersonLocalAccountRecord).filter(
            DirectoryPersonLocalAccountRecord.person_id == source_person.id
        ).first()
        if source_local is not None:
            raise DirectoryConflict(
                "That external identity is already linked to another local account"
            )
        _move_source_memberships(
            db,
            source_person_id=source_person.id,
            target_person_id=target_person.id,
            actor_id=actor_id,
        )
        attachment.person_id = target_person.id
        source_person.state = "merged"
        source_person.merged_into_person_id = target_person.id
        source_person.version += 1
        source_person.updated_at = datetime.utcnow()
        target_person.version += 1
        target_person.updated_at = datetime.utcnow()
        _mirror_legacy_memberships(
            db,
            local_user=user,
            requested=_current_groups(db, target_person.id),
            actor_id=actor_id,
        )
    attachment.link_method = method
    attachment.link_state = "active"
    attachment.review_reason = None
    attachment.actor_id = actor_id
    attachment.updated_at = datetime.utcnow()
    db.add(DirectoryIdentityLinkAuditRecord(
        person_id=target_person.id,
        previous_person_id=previous_person_id,
        external_user_id=external.id,
        action="linked" if source_person.id != target_person.id else "confirmed",
        actor_id=actor_id,
        details=_canonical_json({"method": method}),
    ))
    if external.user_type == "agent" and mirror_legacy_agent:
        _upsert_legacy_agent_link(
            db,
            user=user,
            external=external,
            actor_id=actor_id,
        )
    db.flush()
    return _person_payload(db, target_person.id)


def unlink_external_identity(
    db: Session,
    *,
    attachment_id: int,
    actor_id: Optional[str],
    expected_person_version: Optional[int] = None,
    move_groups: Iterable[str] = (),
    mirror_legacy_agent: bool = True,
) -> dict[str, Any]:
    row = db.query(
        DirectoryPersonExternalIdentityRecord,
        ExternalUserRecord,
    ).join(
        ExternalUserRecord,
        ExternalUserRecord.id
        == DirectoryPersonExternalIdentityRecord.external_user_id,
    ).filter(
        DirectoryPersonExternalIdentityRecord.id == attachment_id
    ).with_for_update().first()
    if row is None:
        raise DirectoryNotFound("Directory identity attachment not found")
    attachment, external = row
    source_person_id = attachment.person_id
    source_person = db.get(DirectoryPersonRecord, source_person_id)
    if expected_person_version is not None and source_person.version != expected_person_version:
        raise DirectoryConflict("Directory person changed; refresh and retry")
    detached = _unlink_attachment_topology(
        db,
        attachment=attachment,
        actor_id=actor_id,
        move_groups=move_groups,
    )
    if external.user_type == "agent" and mirror_legacy_agent:
        link = db.query(UserExternalIdentityLinkRecord).filter(
            UserExternalIdentityLinkRecord.external_user_id == external.id
        ).first()
        if link:
            db.add(UserExternalIdentityAuditRecord(
                user_id=link.user_id,
                external_user_id=link.external_user_id,
                binding_id=link.binding_id,
                provider=link.provider,
                action="unlinked",
                actor_id=actor_id,
                details=_canonical_json({"external_user_id": link.external_user_id}),
            ))
            db.delete(link)
    db.flush()
    return {
        "source_person": _person_payload(db, source_person_id),
        "detached_person": _person_payload(db, detached.id),
    }


def unlink_external_user_identity(
    db: Session,
    *,
    external_user_id: str,
    actor_id: Optional[str],
    expected_person_version: Optional[int] = None,
    move_groups: Iterable[str] = (),
    mirror_legacy_agent: bool = True,
) -> dict[str, Any]:
    attachment = db.query(DirectoryPersonExternalIdentityRecord).filter(
        DirectoryPersonExternalIdentityRecord.external_user_id == external_user_id
    ).first()
    if attachment is None:
        raise DirectoryNotFound("Directory identity attachment not found")
    return unlink_external_identity(
        db,
        attachment_id=attachment.id,
        actor_id=actor_id,
        expected_person_version=expected_person_version,
        move_groups=move_groups,
        mirror_legacy_agent=mirror_legacy_agent,
    )


def preview_exact_email_links(db: Session) -> dict[str, Any]:
    local_by_email: dict[str, list[UserRecord]] = {}
    local_person_ids: dict[str, Optional[str]] = {}
    local_rows = db.query(
        UserRecord,
        DirectoryPersonLocalAccountRecord.person_id,
        DirectoryPersonRecord.state,
    ).outerjoin(
        DirectoryPersonLocalAccountRecord,
        DirectoryPersonLocalAccountRecord.user_id == UserRecord.id,
    ).outerjoin(
        DirectoryPersonRecord,
        DirectoryPersonRecord.id == DirectoryPersonLocalAccountRecord.person_id,
    ).filter(
        UserRecord.is_active.is_(True),
        func.lower(UserRecord.role).in_(("admin", "supervisor", "agent")),
        UserRecord.email_key.isnot(None),
    ).all()
    for user, person_id, person_state in local_rows:
        local_by_email.setdefault(user.email_key, []).append(user)
        local_person_ids[user.id] = person_id if person_state == "active" else None
    external_by_email: dict[
        str,
        list[tuple[ExternalUserRecord, str, Optional[str]]],
    ] = {}
    external_rows = db.query(
        ExternalUserRecord,
        DirectoryPersonExternalIdentityRecord.person_id,
        DirectoryPersonLocalAccountRecord.user_id,
    ).join(
        DirectoryPersonExternalIdentityRecord,
        DirectoryPersonExternalIdentityRecord.external_user_id
        == ExternalUserRecord.id,
    ).outerjoin(
        DirectoryPersonLocalAccountRecord,
        DirectoryPersonLocalAccountRecord.person_id
        == DirectoryPersonExternalIdentityRecord.person_id,
    ).filter(
        ExternalUserRecord.active.is_(True),
        ExternalUserRecord.email.isnot(None),
    ).all()
    for external, person_id, linked_user_id in external_rows:
        email_key = normalize_user_email(external.email)
        if email_key:
            external_by_email.setdefault(email_key, []).append(
                (external, person_id, linked_user_id)
            )

    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for email_key, external_entries in sorted(external_by_email.items()):
        local_rows = local_by_email.get(email_key, [])
        if not local_rows:
            continue
        scopes = {
            (external.binding_id, external.provider)
            for external, _person_id, _linked_user_id in external_entries
        }
        type_counts = {
            user_type: sum(
                external.user_type == user_type
                for external, _person_id, _linked_user_id in external_entries
            )
            for user_type in ("agent", "requester")
        }
        expected_user_ids = {row.id for row in local_rows}
        claimed_elsewhere = any(
            linked_user_id is not None
            and linked_user_id not in expected_user_ids
            for _external, _person_id, linked_user_id in external_entries
        )
        if (
            len(local_rows) != 1
            or len(scopes) != 1
            or any(count > 1 for count in type_counts.values())
            or claimed_elsewhere
        ):
            conflicts.append({
                "email": email_key,
                "local_user_ids": sorted(row.id for row in local_rows),
                "external_user_ids": sorted(
                    external.id
                    for external, _person_id, _linked_user_id in external_entries
                ),
                "reason": "ambiguous_exact_email",
            })
            continue
        local_user = local_rows[0]
        local_person_id = local_person_ids.get(local_user.id)
        if local_person_id is None:
            raise DirectoryNotFound("Local directory person not found")
        for external, external_person_id, _linked_user_id in external_entries:
            if external_person_id == local_person_id:
                continue
            candidates.append({
                "email": email_key,
                "user_id": local_user.id,
                "user_name": local_user.name,
                "external_user_id": external.id,
                "external_name": external.name,
                "user_type": external.user_type,
                "binding_id": external.binding_id,
                "provider": external.provider,
            })
    return {
        "candidates": candidates,
        "conflicts": conflicts,
        "candidate_count": len(candidates),
        "conflict_count": len(conflicts),
    }


def apply_exact_email_links(
    db: Session, *, actor_id: Optional[str]
) -> dict[str, Any]:
    preview = preview_exact_email_links(db)
    linked = 0
    for candidate in preview["candidates"]:
        link_external_identity(
            db,
            user_id=candidate["user_id"],
            external_user_id=candidate["external_user_id"],
            actor_id=actor_id,
            method="auto_exact_email",
            mirror_legacy_agent=True,
        )
        linked += 1
    return {**preview, "linked": linked}


def _acquire_directory_sync_lease(
    *, binding_id: str, provider: str, lease_seconds: int
) -> Optional[str]:
    db = SessionLocal()
    now = datetime.utcnow()
    run_id = str(uuid.uuid4())
    try:
        state = db.query(DirectorySyncStateRecord).filter(
            DirectorySyncStateRecord.binding_id == binding_id,
            DirectorySyncStateRecord.provider == provider,
        ).with_for_update().first()
        if state and state.lease_expires_at and state.lease_expires_at > now:
            return None
        if state is None:
            state = DirectorySyncStateRecord(
                binding_id=binding_id,
                provider=provider,
                last_status="idle",
                last_counts_json="{}",
                updated_at=now,
            )
            db.add(state)
            db.flush()
        state.current_run_id = run_id
        state.lease_expires_at = now + timedelta(seconds=lease_seconds)
        state.last_started_at = now
        state.last_status = "running"
        state.last_error_kind = None
        state.updated_at = now
        db.add(DirectorySyncRunRecord(
            id=run_id,
            binding_id=binding_id,
            provider=provider,
            status="running",
            started_at=now,
            counts_json="{}",
        ))
        db.commit()
        return run_id
    except IntegrityError:
        db.rollback()
        return None
    finally:
        db.close()


def _finish_directory_sync(
    *,
    run_id: str,
    binding_id: str,
    provider: str,
    status: str,
    counts: dict[str, Any],
    error_kind: Optional[str],
) -> None:
    db = SessionLocal()
    now = datetime.utcnow()
    try:
        state = db.query(DirectorySyncStateRecord).filter(
            DirectorySyncStateRecord.binding_id == binding_id,
            DirectorySyncStateRecord.provider == provider,
        ).with_for_update().first()
        run = db.get(DirectorySyncRunRecord, run_id)
        if run:
            run.status = status
            run.finished_at = now
            run.error_kind = error_kind
            run.counts_json = _canonical_json(counts)
        if state and state.current_run_id == run_id:
            state.current_run_id = None
            state.lease_expires_at = None
            state.last_completed_at = now
            state.last_status = status
            state.last_error_kind = error_kind
            state.last_counts_json = _canonical_json(counts)
            state.updated_at = now
            if status == "success":
                state.last_success_at = now
        db.commit()
    finally:
        db.close()


async def run_directory_sync(
    adapter,
    *,
    binding_id: str = "legacy",
    actor_id: Optional[str] = None,
) -> dict[str, Any]:
    provider = str(adapter.provider_name).strip().lower()
    lease_seconds = settings_module.get_int(
        "DIRECTORY_SYNC_LEASE_SECONDS", default=1800, minimum=60, maximum=7200
    )
    run_id = _acquire_directory_sync_lease(
        binding_id=binding_id,
        provider=provider,
        lease_seconds=lease_seconds,
    )
    if run_id is None:
        return {"status": "skipped", "reason": "directory_sync_already_running"}
    result: dict[str, Any] = {}
    status = "failed"
    error_kind: Optional[str] = None
    try:
        result = await async_sync_external_users(adapter, binding_id=binding_id)
        if result.get("errors", 0):
            status = "failed" if not result.get("total", 0) else "partial"
            error_kind = "external_user_sync_failed"
        elif result.get("group_errors", 0):
            status = "partial"
            error_kind = "external_group_sync_failed"
        else:
            db = SessionLocal()
            try:
                projection = ensure_directory_projection(db)
                auto_links = None
                if settings_module.get_bool(
                    "AUTO_EXACT_EMAIL_LINK_ENABLED"
                ):
                    auto_links = apply_exact_email_links(
                        db, actor_id=actor_id
                    )
                db.commit()
                result["projection"] = projection
                if auto_links is not None:
                    result["auto_links"] = {
                        "linked": auto_links["linked"],
                        "conflicts": auto_links["conflict_count"],
                    }
            finally:
                db.close()
            status = "success"
        return {"status": status, "run_id": run_id, "result": result}
    except Exception as exc:
        error_kind = f"directory_sync_failed:{type(exc).__name__}"
        raise
    finally:
        _finish_directory_sync(
            run_id=run_id,
            binding_id=binding_id,
            provider=provider,
            status=status,
            counts=result,
            error_kind=error_kind,
        )


def directory_sync_status(
    db: Session, *, binding_id: str, provider: str
) -> dict[str, Any]:
    state = db.query(DirectorySyncStateRecord).filter(
        DirectorySyncStateRecord.binding_id == binding_id,
        DirectorySyncStateRecord.provider == provider,
    ).first()
    stale_after = settings_module.get_int(
        "DIRECTORY_STALE_AFTER_SECONDS",
        default=86_400,
        minimum=900,
        maximum=2_592_000,
    )
    now = datetime.utcnow()
    if state is None:
        return {
            "binding_id": binding_id,
            "provider": provider,
            "status": "idle",
            "last_started_at": None,
            "last_completed_at": None,
            "last_success_at": None,
            "stale": True,
            "stale_after_seconds": stale_after,
            "error_kind": None,
            "counts": {},
        }
    age = (now - state.last_success_at).total_seconds() if state.last_success_at else None
    try:
        counts = json.loads(state.last_counts_json or "{}")
    except (TypeError, ValueError):
        counts = {}
    return {
        "binding_id": binding_id,
        "provider": provider,
        "status": state.last_status,
        "last_started_at": state.last_started_at,
        "last_completed_at": state.last_completed_at,
        "last_success_at": state.last_success_at,
        "stale": age is None or age > stale_after,
        "stale_after_seconds": stale_after,
        "error_kind": state.last_error_kind,
        "counts": counts if isinstance(counts, dict) else {},
    }
