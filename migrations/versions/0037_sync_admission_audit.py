"""Audit automatic-AI admission for every sync source.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "sync_admission_audit_log" in inspector.get_table_names():
        expected_columns = {
            "id",
            "binding_id",
            "provider",
            "action",
            "actor_id",
            "reason",
            "generation",
            "details",
            "created_at",
        }
        actual_columns = {
            column["name"]
            for column in inspector.get_columns("sync_admission_audit_log")
        }
        if actual_columns != expected_columns:
            raise RuntimeError(
                "sync admission audit schema is partially bootstrapped; apply a forward repair"
            )
        # Historical demo bootstrap can create the exact forward-compatible
        # table from ORM metadata before Alembic reaches this revision.
        return
    op.create_table(
        "sync_admission_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sync_admission_audit_log_action"),
        "sync_admission_audit_log",
        ["action"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sync_admission_audit_log_binding_id"),
        "sync_admission_audit_log",
        ["binding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sync_admission_audit_log_created_at"),
        "sync_admission_audit_log",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sync_admission_audit_log_provider"),
        "sync_admission_audit_log",
        ["provider"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
