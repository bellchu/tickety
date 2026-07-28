"""AI analysis provenance and cross-process claim state.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = [
        sa.Column("ai_source_hash", sa.String(length=64), nullable=True),
        sa.Column("ai_pipeline_version", sa.String(), nullable=True),
        sa.Column("ai_model", sa.String(), nullable=True),
        sa.Column("ai_status", sa.String(), nullable=True),
        sa.Column("ai_claim_id", sa.String(length=36), nullable=True),
        sa.Column("ai_lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("ai_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ai_next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("ai_requested_artifacts", sa.String(), nullable=True),
        sa.Column("ai_started_at", sa.DateTime(), nullable=True),
        sa.Column("ai_generated_at", sa.DateTime(), nullable=True),
        sa.Column("ai_error", sa.String(), nullable=True),
        sa.Column("ai_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_suggested_priority", sa.String(), nullable=True),
    ]
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("tickets")}
    for column in columns:
        if column.name not in existing:
            op.add_column("tickets", column)

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("tickets")}
    if "ix_tickets_ai_source_hash" not in indexes:
        op.create_index("ix_tickets_ai_source_hash", "tickets", ["ai_source_hash"], unique=False)
    if "ix_tickets_ai_status" not in indexes:
        op.create_index("ix_tickets_ai_status", "tickets", ["ai_status"], unique=False)
    for name, column in (
        ("ix_tickets_ai_claim_id", "ai_claim_id"),
        ("ix_tickets_ai_lease_expires_at", "ai_lease_expires_at"),
        ("ix_tickets_ai_next_attempt_at", "ai_next_attempt_at"),
    ):
        if name not in indexes:
            op.create_index(name, "tickets", [column], unique=False)

    # Existing generated artifacts predate provenance and must never be treated
    # as current. They remain visible but are explicitly classified as legacy.
    op.execute(
        """
        UPDATE tickets
        SET ai_status = 'legacy_stale', ai_error = 'provenance_unknown'
        WHERE ai_status IS NULL
          AND (ai_reasoning IS NOT NULL OR summary IS NOT NULL OR recommended_solution IS NOT NULL)
        """
    )

    inspector = sa.inspect(op.get_bind())
    if "ai_usage_events" not in inspector.get_table_names():
        op.create_table(
            "ai_usage_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("actor_id", sa.String(), nullable=False),
            sa.Column("task", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ai_usage_events_actor_id", "ai_usage_events", ["actor_id"], unique=False)
        op.create_index("ix_ai_usage_events_created_at", "ai_usage_events", ["created_at"], unique=False)

    inspector = sa.inspect(op.get_bind())
    if "ai_request_buckets" not in inspector.get_table_names():
        op.create_table(
            "ai_request_buckets",
            sa.Column("actor_id", sa.String(), nullable=False),
            sa.Column("window_kind", sa.String(), nullable=False),
            sa.Column("window_start", sa.DateTime(), nullable=False),
            sa.Column("request_count", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("actor_id", "window_kind", "window_start"),
        )

    inspector = sa.inspect(op.get_bind())
    if "llm_call_records" not in inspector.get_table_names():
        op.create_table(
            "llm_call_records",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("task", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False),
            sa.Column("completion_tokens", sa.Integer(), nullable=False),
            sa.Column("total_tokens", sa.Integer(), nullable=False),
            sa.Column("synthetic", sa.Boolean(), nullable=False),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_llm_call_records_provider", "llm_call_records", ["provider"], unique=False)
        op.create_index("ix_llm_call_records_status", "llm_call_records", ["status"], unique=False)
        op.create_index("ix_llm_call_records_created_at", "llm_call_records", ["created_at"], unique=False)

    inspector = sa.inspect(op.get_bind())
    if "ai_artifact_records" not in inspector.get_table_names():
        op.create_table(
            "ai_artifact_records",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("ticket_id", sa.String(), nullable=False),
            sa.Column("artifact", sa.String(), nullable=False),
            sa.Column("input_hash", sa.String(length=64), nullable=False),
            sa.Column("pipeline_version", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("synthetic", sa.Boolean(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for name, column in (
            ("ix_ai_artifact_records_ticket_id", "ticket_id"),
            ("ix_ai_artifact_records_artifact", "artifact"),
            ("ix_ai_artifact_records_input_hash", "input_hash"),
            ("ix_ai_artifact_records_active", "active"),
        ):
            op.create_index(name, "ai_artifact_records", [column], unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
