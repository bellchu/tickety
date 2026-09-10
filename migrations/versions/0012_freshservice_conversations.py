"""Add Freshservice projection and explicit automatic-AI boundary state.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column_type in (
        ("external_group_id", sa.String()),
        ("external_status_code", sa.String(length=64)),
        ("external_priority_code", sa.String(length=64)),
        ("external_ticket_type_raw", sa.String(length=255)),
        ("external_source_context_hash", sa.String(length=64)),
        ("external_category", sa.String()),
        ("external_subcategory", sa.String()),
        ("external_item_category", sa.String()),
        ("external_conversation_text", sa.Text()),
        ("external_conversation_updated_at", sa.DateTime()),
    ):
        op.add_column("tickets", sa.Column(name, column_type, nullable=True))

    op.add_column(
        "sync_state",
        sa.Column(
            "automatic_ai_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "sync_state", sa.Column("automatic_ai_generation", sa.Integer(), nullable=True)
    )
    op.add_column(
        "sync_state", sa.Column("automatic_ai_cutover_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "sync_state", sa.Column("automatic_ai_enabled_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "sync_state", sa.Column("automatic_ai_enabled_by", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "sync_state", sa.Column("automatic_ai_paused_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "sync_state", sa.Column("automatic_ai_paused_by", sa.String(length=255), nullable=True)
    )
    op.create_index(
        "ix_sync_state_automatic_ai_enabled",
        "sync_state",
        ["automatic_ai_enabled"],
    )
    with op.batch_alter_table("sync_state") as batch_op:
        batch_op.create_check_constraint(
            "ck_sync_state_automatic_ai_boundary",
            "automatic_ai_enabled = FALSE OR "
            "(automatic_ai_generation IS NOT NULL AND "
            "automatic_ai_cutover_at IS NOT NULL AND "
            "automatic_ai_enabled_at IS NOT NULL)",
        )

    op.add_column(
        "ticket_comments", sa.Column("external_source", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "ticket_comments", sa.Column("external_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "ticket_comments", sa.Column("external_author_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "ticket_comments", sa.Column("external_updated_at", sa.DateTime(), nullable=True)
    )
    with op.batch_alter_table("ticket_comments") as batch_op:
        batch_op.create_unique_constraint(
            "uix_ticket_external_comment",
            ["ticket_id", "external_source", "external_id"],
        )

    op.create_table(
        "external_conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=False),
        sa.Column("provider_ticket_id", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("incoming", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.Integer(), nullable=True),
        sa.Column("author_external_id", sa.String(length=255), nullable=True),
        sa.Column("provider_created_at", sa.DateTime(), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "public_tombstone", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("projection_version", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id", "provider", "provider_ticket_id", "external_id",
            name="uix_external_conversation_identity",
        ),
    )
    op.create_index(
        "ix_external_conversations_ticket_current",
        "external_conversations",
        ["binding_id", "provider", "provider_ticket_id", "deleted", "is_private"],
    )
    op.create_index(
        "ix_external_conversations_ticket_id",
        "external_conversations",
        ["ticket_id"],
    )
    for column in (
        "binding_id",
        "provider",
        "provider_ticket_id",
        "is_private",
        "deleted",
        "public_tombstone",
        "revision_hash",
    ):
        op.create_index(
            f"ix_external_conversations_{column}",
            "external_conversations",
            [column],
        )

    op.create_table(
        "external_activity_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("activity_at", sa.DateTime(), nullable=True),
        sa.Column("acquisition_mode", sa.String(length=32), nullable=False),
        sa.Column("automatic_ai_generation", sa.Integer(), nullable=True),
        sa.Column("automatic_ai_eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.String(length=96), nullable=False),
        sa.Column("affected_artifacts", sa.String(length=255), nullable=True),
        sa.Column("projected_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id", "provider", "ticket_id", "entity_type", "external_id",
            "revision_hash",
            name="uix_external_activity_revision",
        ),
        sa.CheckConstraint(
            "automatic_ai_eligible = FALSE OR "
            "(activity_at IS NOT NULL AND automatic_ai_generation IS NOT NULL)",
            name="ck_external_activity_eligible_evidence",
        ),
    )
    op.create_index(
        "ix_external_activity_ledger_ticket_id",
        "external_activity_ledger",
        ["ticket_id"],
    )
    for column in (
        "binding_id",
        "provider",
        "activity_at",
        "automatic_ai_eligible",
    ):
        op.create_index(
            f"ix_external_activity_ledger_{column}",
            "external_activity_ledger",
            [column],
        )

    op.create_table(
        "external_ticket_context",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=False),
        sa.Column("provider_ticket_id", sa.String(length=255), nullable=False),
        sa.Column("status_raw", sa.String(length=64), nullable=True),
        sa.Column("status_mapped", sa.String(length=120), nullable=True),
        sa.Column("priority_raw", sa.String(length=64), nullable=True),
        sa.Column("priority_mapped", sa.String(length=120), nullable=True),
        sa.Column("ticket_type_raw", sa.String(length=255), nullable=True),
        sa.Column("ticket_type_mapped", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("subcategory", sa.String(length=255), nullable=True),
        sa.Column("item_category", sa.String(length=255), nullable=True),
        sa.Column("group_external_id", sa.String(length=255), nullable=True),
        sa.Column("responder_external_id", sa.String(length=255), nullable=True),
        sa.Column("requester_external_id", sa.String(length=255), nullable=True),
        sa.Column("workspace_external_id", sa.String(length=255), nullable=True),
        sa.Column("provider_created_at", sa.DateTime(), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(), nullable=True),
        sa.Column("provider_resolved_at", sa.DateTime(), nullable=True),
        sa.Column("provider_due_at", sa.DateTime(), nullable=True),
        sa.Column("source_context_hash", sa.String(length=64), nullable=False),
        sa.Column("projection_version", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id", "provider", "provider_ticket_id",
            name="uix_external_ticket_context_identity",
        ),
    )
    for column in ("binding_id", "provider", "ticket_id"):
        op.create_index(
            f"ix_external_ticket_context_{column}",
            "external_ticket_context",
            [column],
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
