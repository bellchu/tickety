"""Cross-process LLM provider concurrency leases.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "llm_provider_leases" not in inspector.get_table_names():
        op.create_table(
            "llm_provider_leases",
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("slot", sa.Integer(), nullable=False),
            sa.Column("owner_id", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("provider", "slot"),
        )
        op.create_index(
            "ix_llm_provider_leases_owner_id", "llm_provider_leases", ["owner_id"]
        )
        op.create_index(
            "ix_llm_provider_leases_expires_at", "llm_provider_leases", ["expires_at"]
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
