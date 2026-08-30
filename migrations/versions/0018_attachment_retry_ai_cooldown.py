"""Back off attachment copies and persist provider-wide AI cooldowns.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "external_attachments",
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_external_attachments_next_attempt_at",
        "external_attachments",
        ["next_attempt_at"],
    )
    op.create_table(
        "llm_provider_cooldowns",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "reason",
            sa.String(length=64),
            nullable=False,
            server_default="provider_capacity",
        ),
        sa.Column("retry_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("provider"),
    )
    op.create_index(
        "ix_llm_provider_cooldowns_retry_at",
        "llm_provider_cooldowns",
        ["retry_at"],
    )

    # Freshservice can rotate an attachment ID while retaining the same file
    # in the same owner snapshot. A successfully stored replacement proves the
    # old failed URL is obsolete, so remove that stale row from the error lane.
    op.execute("""
        UPDATE external_attachments AS old
        SET storage_status = 'superseded',
            source_url = NULL,
            last_error = NULL,
            next_attempt_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE old.storage_status = 'error'
          AND EXISTS (
              SELECT 1
              FROM external_attachments AS replacement
              WHERE replacement.binding_id = old.binding_id
                AND replacement.provider = old.provider
                AND replacement.provider_ticket_id = old.provider_ticket_id
                AND replacement.owner_type = old.owner_type
                AND replacement.owner_external_id = old.owner_external_id
                AND replacement.external_id <> old.external_id
                AND replacement.file_name = old.file_name
                AND COALESCE(replacement.content_type, '') = COALESCE(old.content_type, '')
                AND COALESCE(replacement.declared_size, -1) = COALESCE(old.declared_size, -1)
                AND replacement.storage_status = 'stored'
          )
    """)


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
