"""Persist one-time Intelligence study snapshots.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intelligence_studies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("study_type", sa.String(length=64), nullable=False),
        sa.Column("period_months", sa.Integer(), nullable=False),
        sa.Column("range_start_at", sa.DateTime(), nullable=False),
        sa.Column("range_end_at", sa.DateTime(), nullable=False),
        sa.Column("source_data_through_at", sa.DateTime(), nullable=True),
        sa.Column("analyzed_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_intelligence_studies_study_type",
        "intelligence_studies",
        ["study_type"],
    )
    op.create_index(
        "ix_intelligence_studies_created_at",
        "intelligence_studies",
        ["created_at"],
    )
    op.create_index(
        "ix_intelligence_studies_latest",
        "intelligence_studies",
        ["study_type", "period_months", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
