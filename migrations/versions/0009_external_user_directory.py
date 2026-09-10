"""Separate Tickety users from the external ITSM user directory.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    op.create_table(
        "external_users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False, server_default="legacy"),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("user_type", sa.String(length=32), nullable=False, server_default="agent"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("profile_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "binding_id", "provider", "user_type", "external_id",
            name="uix_external_user_identity",
        ),
    )
    op.create_index("ix_external_users_binding_id", "external_users", ["binding_id"])
    op.create_index("ix_external_users_provider", "external_users", ["provider"])
    op.create_index("ix_external_users_user_type", "external_users", ["user_type"])
    op.create_index("ix_external_users_active", "external_users", ["active"])
    op.create_index(
        "ix_external_users_lookup",
        "external_users",
        ["binding_id", "provider", "external_id"],
    )

    # Existing provider-created accounts are not deleted: their profile history
    # may already be referenced by local records. Accounts that were never login
    # capable are deactivated before the obsolete identity bridge is removed.
    bind = op.get_bind()
    if sa.inspect(bind).has_table("user_mappings"):
        bind.execute(sa.text("""
            UPDATE users
               SET is_active = false
             WHERE password_hash IS NULL
               AND id IN (SELECT tickety_user_id FROM user_mappings)
        """))
        op.drop_table("user_mappings")

    # Embedded sessions now carry a constrained provider identity only; they
    # are never promoted into a Tickety user session.
    with op.batch_alter_table(
        "integration_sessions", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_index("ix_integration_sessions_user_id")
        batch_op.drop_column("user_id")


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
