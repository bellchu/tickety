"""Add canonical directory people and guarded remote team membership.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-26
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RESOLVER_GROUP_CHECK = (
    "resolver_group IN ("
    "'SERVICE_DESK','NETWORK_OPERATIONS','INFRASTRUCTURE_OPERATIONS','CLOUD_PLATFORM',"
    "'BUSINESS_APPLICATIONS','AUTOMATION_SERVICES','DATA_SERVICES','APPLICATION_OPERATIONS',"
    "'IDENTITY_ACCESS','ENDPOINT_SUPPORT','SECURITY_OPERATIONS','SOFTWARE_ENGINEERING','INTEGRATION_SERVICES','SERVICE_DELIVERY')"
)


def _create_schema() -> None:
    op.create_table(
        "directory_people",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("merged_into_person_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(state = 'active' AND merged_into_person_id IS NULL) OR "
            "(state = 'merged' AND merged_into_person_id IS NOT NULL)",
            name="ck_directory_person_lifecycle",
        ),
        sa.CheckConstraint("version >= 1", name="ck_directory_person_version"),
        sa.ForeignKeyConstraint(
            ["merged_into_person_id"], ["directory_people.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_directory_people_state", "directory_people", ["state"], unique=False
    )
    op.create_index(
        "ix_directory_people_merged_into_person_id",
        "directory_people",
        ["merged_into_person_id"],
        unique=False,
    )

    op.create_table(
        "directory_person_local_accounts",
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"], ["directory_people.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("person_id"),
        sa.UniqueConstraint("person_id", name="uix_directory_person_local_person"),
        sa.UniqueConstraint("user_id", name="uix_directory_person_local_user"),
    )
    op.create_index(
        "ix_directory_person_local_accounts_user_id",
        "directory_person_local_accounts",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "directory_person_external_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("external_user_id", sa.String(length=36), nullable=False),
        sa.Column("link_method", sa.String(length=32), nullable=False),
        sa.Column("link_state", sa.String(length=24), nullable=False),
        sa.Column("review_reason", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "link_method IN ('source','backfill_manual','manual','auto_exact_email')",
            name="ck_directory_person_external_link_method",
        ),
        sa.CheckConstraint(
            "link_state IN ('active','review_required')",
            name="ck_directory_person_external_link_state",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["external_user_id"], ["external_users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["directory_people.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_user_id", name="uix_directory_person_external_identity"
        ),
    )
    op.create_index(
        "ix_directory_person_external_identities_person_id",
        "directory_person_external_identities",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_directory_person_external_identities_external_user_id",
        "directory_person_external_identities",
        ["external_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_directory_person_external_identities_link_state",
        "directory_person_external_identities",
        ["link_state"],
        unique=False,
    )
    op.create_index(
        "ix_directory_person_external_person_state",
        "directory_person_external_identities",
        ["person_id", "link_state"],
        unique=False,
    )

    op.create_table(
        "directory_person_resolver_team_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("resolver_group", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _RESOLVER_GROUP_CHECK, name="ck_directory_person_resolver_group_code"
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_directory_person_resolver_team_version"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["directory_people.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "resolver_group",
            name="uix_directory_person_resolver_team_membership",
        ),
    )
    op.create_index(
        "ix_directory_person_resolver_team_lookup",
        "directory_person_resolver_team_mappings",
        ["resolver_group", "person_id"],
        unique=False,
    )

    op.create_table(
        "directory_person_resolver_team_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("previous_groups", sa.Text(), nullable=False),
        sa.Column("new_groups", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_directory_person_resolver_team_audit_subject",
        "directory_person_resolver_team_audit",
        ["person_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "directory_identity_link_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("previous_person_id", sa.String(length=36), nullable=True),
        sa.Column("external_user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_directory_identity_link_audit_person_id",
        "directory_identity_link_audit",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_directory_identity_link_audit_external_user_id",
        "directory_identity_link_audit",
        ["external_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_directory_identity_link_audit_created_at",
        "directory_identity_link_audit",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "directory_sync_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("current_run_id", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=24), nullable=False),
        sa.Column("last_error_kind", sa.String(length=96), nullable=True),
        sa.Column("last_counts_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "last_status IN ('idle','running','success','failed','partial','skipped')",
            name="ck_directory_sync_state_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id", "provider", name="uix_directory_sync_state_scope"
        ),
    )
    op.create_index(
        "ix_directory_sync_state_lease_expires_at",
        "directory_sync_state",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_directory_sync_state_last_success_at",
        "directory_sync_state",
        ["last_success_at"],
        unique=False,
    )

    op.create_table(
        "directory_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_kind", sa.String(length=96), nullable=True),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','success','failed','partial','skipped')",
            name="ck_directory_sync_run_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_directory_sync_runs_binding_id",
        "directory_sync_runs",
        ["binding_id"],
        unique=False,
    )
    op.create_index(
        "ix_directory_sync_runs_provider",
        "directory_sync_runs",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_directory_sync_runs_status",
        "directory_sync_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_directory_sync_runs_scope_started",
        "directory_sync_runs",
        ["binding_id", "provider", "started_at"],
        unique=False,
    )


def _insert_person(bind, now: datetime) -> str:
    person_id = str(uuid.uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO directory_people "
            "(id, state, merged_into_person_id, version, created_at, updated_at) "
            "VALUES (:id, 'active', NULL, 1, :now, :now)"
        ),
        {"id": person_id, "now": now},
    )
    return person_id


def _backfill(bind) -> None:
    now = datetime.utcnow()
    local_people = {
        row.user_id: row.person_id
        for row in bind.execute(sa.text(
            "SELECT user_id, person_id FROM directory_person_local_accounts"
        )).mappings()
    }
    for row in bind.execute(sa.text("SELECT id FROM users ORDER BY id")).mappings():
        if row.id in local_people:
            continue
        person_id = _insert_person(bind, now)
        bind.execute(
            sa.text(
                "INSERT INTO directory_person_local_accounts "
                "(person_id, user_id, created_at) VALUES (:person_id, :user_id, :now)"
            ),
            {"person_id": person_id, "user_id": row.id, "now": now},
        )
        local_people[row.id] = person_id

    manual_links = {
        row.external_user_id: row
        for row in bind.execute(sa.text(
            "SELECT user_id, external_user_id, created_by, created_at, updated_at "
            "FROM user_external_identity_links"
        )).mappings()
    }
    attached_external_ids = {
        row.external_user_id
        for row in bind.execute(sa.text(
            "SELECT external_user_id FROM directory_person_external_identities"
        )).mappings()
    }
    for row in bind.execute(sa.text(
        "SELECT id FROM external_users ORDER BY binding_id, provider, user_type, external_id"
    )).mappings():
        if row.id in attached_external_ids:
            continue
        manual = manual_links.get(row.id)
        if manual is not None and manual.user_id in local_people:
            person_id = local_people[manual.user_id]
            method = "backfill_manual"
            actor_id = manual.created_by
            created_at = manual.created_at or now
            updated_at = manual.updated_at or created_at
        else:
            person_id = _insert_person(bind, now)
            method = "source"
            actor_id = None
            created_at = now
            updated_at = now
        bind.execute(
            sa.text(
                "INSERT INTO directory_person_external_identities "
                "(person_id, external_user_id, link_method, link_state, "
                "review_reason, actor_id, created_at, updated_at) VALUES "
                "(:person_id, :external_user_id, :method, 'active', NULL, "
                ":actor_id, :created_at, :updated_at)"
            ),
            {
                "person_id": person_id,
                "external_user_id": row.id,
                "method": method,
                "actor_id": actor_id,
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )

    grouped: dict[str, list[str]] = {}
    for row in bind.execute(sa.text(
        "SELECT user_id, resolver_group, created_by, created_at, updated_at "
        "FROM agent_resolver_team_mappings ORDER BY user_id, resolver_group"
    )).mappings():
        person_id = local_people.get(row.user_id)
        if person_id is None:
            continue
        existing = bind.execute(
            sa.text(
                "SELECT 1 FROM directory_person_resolver_team_mappings "
                "WHERE person_id = :person_id AND resolver_group = :resolver_group"
            ),
            {"person_id": person_id, "resolver_group": row.resolver_group},
        ).first()
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO directory_person_resolver_team_mappings "
                    "(person_id, resolver_group, version, created_by, created_at, updated_at) "
                    "VALUES (:person_id, :resolver_group, 1, :created_by, "
                    ":created_at, :updated_at)"
                ),
                {
                    "person_id": person_id,
                    "resolver_group": row.resolver_group,
                    "created_by": row.created_by,
                    "created_at": row.created_at or now,
                    "updated_at": row.updated_at or row.created_at or now,
                },
            )
        grouped.setdefault(person_id, []).append(row.resolver_group)

    for person_id, groups in grouped.items():
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM directory_person_resolver_team_audit "
                "WHERE person_id = :person_id AND action = 'backfilled'"
            ),
            {"person_id": person_id},
        ).first()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO directory_person_resolver_team_audit "
                    "(person_id, actor_id, action, previous_groups, new_groups, "
                    "details, created_at) VALUES "
                    "(:person_id, NULL, 'backfilled', '[]', :groups, :details, :now)"
                ),
                {
                    "person_id": person_id,
                    "groups": json.dumps(sorted(set(groups)), separators=(",", ":")),
                    "details": json.dumps(
                        {"source": "agent_resolver_team_mappings"},
                        separators=(",", ":"),
                    ),
                    "now": now,
                },
            )


def upgrade() -> None:
    managed_tables = {
        "directory_people",
        "directory_person_local_accounts",
        "directory_person_external_identities",
        "directory_person_resolver_team_mappings",
        "directory_person_resolver_team_audit",
        "directory_identity_link_audit",
        "directory_sync_state",
        "directory_sync_runs",
    }
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    existing_managed = managed_tables.intersection(existing_tables)
    if existing_managed and existing_managed != managed_tables:
        raise RuntimeError(
            "directory people schema is partially bootstrapped; apply a forward repair"
        )
    if not existing_managed:
        _create_schema()
    _backfill(op.get_bind())


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
