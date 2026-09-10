"""Add short-lived Freshworks embedded sessions.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "integration_bootstrap_codes",
        sa.Column("context_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "integration_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", sa.String(length=255), nullable=True),
        sa.Column("external_ticket_id", sa.String(length=255), nullable=True),
        sa.Column("audience", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_bindings.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        "ix_integration_sessions_binding_id", "integration_sessions", ["binding_id"]
    )
    op.create_index(
        "ix_integration_sessions_user_id", "integration_sessions", ["user_id"]
    )
    op.create_index(
        "ix_integration_sessions_expires_at", "integration_sessions", ["expires_at"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
