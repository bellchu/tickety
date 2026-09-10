"""Add Tickety-owned agent memberships and structured routing rules.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RESOLVER_GROUP_CHECK = (
    "resolver_group IN ("
    "'SERVICE_DESK','NETWORK_OPERATIONS','INFRASTRUCTURE_OPERATIONS','CLOUD_PLATFORM',"
    "'BUSINESS_APPLICATIONS','AUTOMATION_SERVICES','DATA_SERVICES','APPLICATION_OPERATIONS',"
    "'IDENTITY_ACCESS','ENDPOINT_SUPPORT','SECURITY_OPERATIONS','SOFTWARE_ENGINEERING','INTEGRATION_SERVICES','SERVICE_DELIVERY')"
)


def upgrade() -> None:
    managed_tables = {
        "agent_resolver_team_mappings",
        "agent_resolver_team_mapping_audit",
        "routing_rules",
        "routing_rule_audit",
    }
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    existing_managed_tables = managed_tables.intersection(existing_tables)
    if existing_managed_tables == managed_tables:
        # Historical demo bootstrap can create the exact forward-compatible
        # metadata before Alembic reaches this revision. Adopt it in place.
        return
    if existing_managed_tables:
        raise RuntimeError(
            "routing management schema is partially bootstrapped; apply a forward repair"
        )
    op.create_table(
        "agent_resolver_team_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("resolver_group", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            _RESOLVER_GROUP_CHECK,
            name="ck_agent_resolver_group_code",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "resolver_group",
            name="uix_agent_resolver_team_membership",
        ),
    )
    op.create_index(
        "ix_agent_resolver_team_lookup",
        "agent_resolver_team_mappings",
        ["resolver_group", "user_id"],
        unique=False,
    )
    op.create_table(
        "agent_resolver_team_mapping_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("previous_groups", sa.Text(), nullable=False),
        sa.Column("new_groups", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_resolver_team_audit_subject",
        "agent_resolver_team_mapping_audit",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=True),
        sa.Column("service_contains", sa.String(length=80), nullable=True),
        sa.Column("failure_domain_contains", sa.String(length=80), nullable=True),
        sa.Column("primary_group", sa.String(length=32), nullable=False),
        sa.Column("secondary_group", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("priority BETWEEN 1 AND 1000", name="ck_routing_rule_priority"),
        sa.CheckConstraint("version >= 1", name="ck_routing_rule_version"),
        sa.CheckConstraint(
            "scope IS NOT NULL OR service_contains IS NOT NULL OR "
            "failure_domain_contains IS NOT NULL",
            name="ck_routing_rule_has_condition",
        ),
        sa.CheckConstraint(
            "scope IS NULL OR scope IN ('single_user','multiple_users','service_wide','unknown')",
            name="ck_routing_rule_scope",
        ),
        sa.CheckConstraint(_RESOLVER_GROUP_CHECK.replace("resolver_group", "primary_group"), name="ck_routing_rule_primary_group"),
        sa.CheckConstraint(
            "secondary_group IS NULL OR " + _RESOLVER_GROUP_CHECK.replace("resolver_group", "secondary_group"),
            name="ck_routing_rule_secondary_group",
        ),
        sa.CheckConstraint(
            "secondary_group IS NULL OR secondary_group <> primary_group",
            name="ck_routing_rule_distinct_groups",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_routing_rules_active_priority",
        "routing_rules",
        ["enabled", "priority", "id"],
        unique=False,
    )
    op.create_table(
        "routing_rule_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("previous_snapshot", sa.Text(), nullable=True),
        sa.Column("new_snapshot", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_routing_rule_audit_subject",
        "routing_rule_audit",
        ["rule_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
