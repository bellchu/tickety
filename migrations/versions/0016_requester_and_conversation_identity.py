"""Preserve requester and conversation author identity.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("external_requester_id", sa.String(length=255), nullable=True))
    op.add_column("tickets", sa.Column("external_requester_name", sa.String(length=255), nullable=True))
    op.add_column("tickets", sa.Column("external_requester_email", sa.String(length=320), nullable=True))
    op.add_column("tickets", sa.Column("external_requester_title", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_tickets_external_requester_id", "tickets", ["external_requester_id"]
    )

    op.add_column("ticket_comments", sa.Column("author_email", sa.String(length=320), nullable=True))
    op.add_column("external_conversations", sa.Column("author_name", sa.String(length=255), nullable=True))
    op.add_column("external_conversations", sa.Column("author_email", sa.String(length=320), nullable=True))

    # Existing provider threads must be observed once more so identity fields
    # can be populated from the authoritative conversation envelope.
    op.execute(
        "UPDATE tickets SET external_conversations_synced_at = NULL "
        "WHERE external_source = 'freshservice' AND EXISTS ("
        "SELECT 1 FROM ticket_comments "
        "WHERE ticket_comments.ticket_id = tickets.id "
        "AND ticket_comments.external_source = 'freshservice'"
        ")"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
