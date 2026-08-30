"""Add lossless Freshservice content and private attachment storage state.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("external_description_html", sa.Text(), nullable=True))
    op.add_column("external_conversations", sa.Column("body_html", sa.Text(), nullable=True))

    op.create_table(
        "external_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=False),
        sa.Column("provider_ticket_id", sa.String(length=255), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_external_id", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("declared_size", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("blob_key", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("stored_size", sa.Integer(), nullable=True),
        sa.Column("storage_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(), nullable=True),
        sa.Column("stored_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "owner_type IN ('ticket', 'conversation')",
            name="ck_external_attachment_owner_type",
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id", "provider", "provider_ticket_id", "owner_type",
            "owner_external_id", "external_id",
            name="uix_external_attachment_identity",
        ),
    )
    for column in (
        "binding_id", "provider", "ticket_id", "provider_ticket_id",
        "content_sha256", "storage_status",
    ):
        op.create_index(
            f"ix_external_attachments_{column}", "external_attachments", [column]
        )
    op.create_index(
        "ix_external_attachments_ticket_status",
        "external_attachments",
        ["ticket_id", "storage_status"],
    )
    # Rehydrate previously completed Freshservice threads once so full HTML
    # and attachment metadata are backfilled through the bounded worker lane.
    op.execute(
        "UPDATE tickets SET external_conversations_synced_at = NULL "
        "WHERE external_source = 'freshservice'"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
