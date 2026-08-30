"""Add a durable repair cursor for provider ticket timestamps.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    expected_columns = {
        "provider_timestamp_repair_version",
        "provider_timestamp_repair_started_at",
        "provider_timestamp_repair_completed_at",
        "provider_timestamp_repair_page",
        "provider_timestamp_repair_workspace_index",
        "provider_timestamp_repair_processed",
    }
    actual_columns = {
        column["name"] for column in inspector.get_columns("sync_state")
    }
    adopted_columns = actual_columns & expected_columns
    if adopted_columns:
        if adopted_columns != expected_columns:
            raise RuntimeError(
                "provider timestamp repair schema is partially bootstrapped; "
                "apply a forward repair"
            )
        # Historical demo bootstrap can create the exact forward-compatible
        # columns from ORM metadata before Alembic reaches this revision.
        return
    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "provider_timestamp_repair_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "provider_timestamp_repair_started_at",
            sa.DateTime(),
            nullable=True,
        ))
        batch_op.add_column(sa.Column(
            "provider_timestamp_repair_completed_at",
            sa.DateTime(),
            nullable=True,
        ))
        batch_op.add_column(sa.Column(
            "provider_timestamp_repair_page",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ))
        batch_op.add_column(sa.Column(
            "provider_timestamp_repair_workspace_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))
        batch_op.add_column(sa.Column(
            "provider_timestamp_repair_processed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
