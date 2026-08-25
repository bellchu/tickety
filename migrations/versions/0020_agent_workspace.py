"""Add provider-backed Agent workspace identity and mailbox state.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_groups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False, server_default="legacy"),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("profile_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id", "provider", "external_id",
            name="uix_external_group_identity",
        ),
    )
    op.create_index("ix_external_groups_binding_id", "external_groups", ["binding_id"])
    op.create_index("ix_external_groups_provider", "external_groups", ["provider"])
    op.create_index("ix_external_groups_workspace_id", "external_groups", ["workspace_id"])
    op.create_index("ix_external_groups_active", "external_groups", ["active"])
    op.create_index(
        "ix_external_groups_lookup",
        "external_groups",
        ["binding_id", "provider", "external_id"],
    )

    op.create_table(
        "external_group_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_group_id", sa.String(length=36), nullable=False),
        sa.Column("external_user_id", sa.String(length=36), nullable=False),
        sa.Column("membership_kind", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "membership_kind IN ('member', 'observer')",
            name="ck_external_group_membership_kind",
        ),
        sa.ForeignKeyConstraint(["external_group_id"], ["external_groups.id"]),
        sa.ForeignKeyConstraint(["external_user_id"], ["external_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_group_id", "external_user_id", "membership_kind",
            name="uix_external_group_membership",
        ),
    )
    op.create_index(
        "ix_external_group_memberships_external_group_id",
        "external_group_memberships",
        ["external_group_id"],
    )
    op.create_index(
        "ix_external_group_memberships_external_user_id",
        "external_group_memberships",
        ["external_user_id"],
    )

    op.create_table(
        "user_external_identity_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("external_user_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["external_user_id"], ["external_users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_user_id"),
        sa.UniqueConstraint(
            "user_id", "binding_id", "provider",
            name="uix_user_external_identity_binding",
        ),
    )
    op.create_index("ix_user_external_identity_links_user_id", "user_external_identity_links", ["user_id"])
    op.create_index("ix_user_external_identity_links_external_user_id", "user_external_identity_links", ["external_user_id"], unique=True)
    op.create_index("ix_user_external_identity_links_binding_id", "user_external_identity_links", ["binding_id"])
    op.create_index("ix_user_external_identity_links_provider", "user_external_identity_links", ["provider"])
    op.create_index(
        "ix_user_external_identity_scope",
        "user_external_identity_links",
        ["user_id", "binding_id", "provider"],
    )

    op.create_table(
        "user_external_identity_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("external_user_id", sa.String(length=36), nullable=True),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_external_identity_audit_user_id", "user_external_identity_audit", ["user_id"])
    op.create_index("ix_user_external_identity_audit_binding_id", "user_external_identity_audit", ["binding_id"])
    op.create_index("ix_user_external_identity_audit_created_at", "user_external_identity_audit", ["created_at"])

    op.create_table(
        "agent_ticket_state",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("starred_at", sa.DateTime(), nullable=True),
        sa.Column("follow_up_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "ticket_id"),
    )
    op.create_index("ix_agent_ticket_state_starred_at", "agent_ticket_state", ["starred_at"])
    op.create_index("ix_agent_ticket_state_follow_up_at", "agent_ticket_state", ["follow_up_at"])


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
