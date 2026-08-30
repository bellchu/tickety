"""Expire legacy sessions and index hot operational lookups.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = (
    (
        "ix_ai_request_buckets_window_start",
        "ai_request_buckets",
        ("window_start",),
    ),
    ("ix_sessions_expires_at", "sessions", ("expires_at",)),
    ("ix_users_name_id", "users", ("name", "id")),
    (
        "ix_users_active_name_id",
        "users",
        ("is_active", "name", "id"),
    ),
    ("ix_users_active_role", "users", ("is_active", "role")),
    (
        "ix_external_conversations_ticket_external_private",
        "external_conversations",
        ("ticket_id", "external_id", "is_private"),
    ),
    (
        "ix_external_attachments_ticket_created_id",
        "external_attachments",
        ("ticket_id", "created_at", "id"),
    ),
    (
        "ix_change_approvals_approver_state",
        "change_approvals",
        ("approver_id", "decided_at", "decision"),
    ),
    (
        "ix_tickets_resolved_by_at",
        "tickets",
        ("resolved_by", "resolved_at"),
    ),
    (
        "ix_agent_ticket_state_ticket_id",
        "agent_ticket_state",
        ("ticket_id",),
    ),
)

_SERVICE_REQUEST_INDEXES = (
    (
        "ix_service_requests_created_id",
        "created_at DESC, id ASC",
        "created_at DESC, id ASC",
    ),
    (
        "ix_service_requests_service_created_id",
        "service_item_id, created_at DESC, id ASC",
        "service_item_id, created_at DESC, id ASC",
    ),
    (
        "ix_service_requests_approval_created_id",
        "approval_status, created_at DESC, id ASC",
        "approval_status, created_at DESC, id ASC",
    ),
    (
        "ix_service_requests_fulfillment_created_id",
        "fulfillment_status, created_at DESC, id ASC",
        "fulfillment_status, created_at DESC, id ASC",
    ),
)


def _backfill_session_expiry(bind) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(
            "UPDATE sessions "
            "SET expires_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
            "+ INTERVAL '14 days' "
            "WHERE expires_at IS NULL"
        ))
    else:
        op.execute(sa.text(
            "UPDATE sessions "
            "SET expires_at = datetime(COALESCE(created_at, CURRENT_TIMESTAMP), '+14 days') "
            "WHERE expires_at IS NULL"
        ))


def _backfill_service_request_created_at() -> None:
    op.execute(sa.text(
        "UPDATE service_requests "
        "SET created_at = '1970-01-01 00:00:00' "
        "WHERE created_at IS NULL"
    ))


def _create_indexes(bind) -> None:
    if bind.dialect.name == "postgresql":
        # These relations can be large. Keep reads and writes available while
        # the migration builds its secondary indexes. A failed concurrent
        # build can leave an invalid index behind, so every retry drops the
        # target before rebuilding it instead of trusting IF NOT EXISTS.
        with op.get_context().autocommit_block():
            for name, table, columns in _INDEXES:
                column_sql = ", ".join(f'"{column}"' for column in columns)
                op.execute(sa.text(
                    f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'
                ))
                op.execute(sa.text(
                    f'CREATE INDEX CONCURRENTLY "{name}" '
                    f'ON "{table}" ({column_sql})'
                ))
            for name, postgresql_columns, _sqlite_columns in _SERVICE_REQUEST_INDEXES:
                op.execute(sa.text(
                    f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'
                ))
                op.execute(sa.text(
                    f'CREATE INDEX CONCURRENTLY "{name}" '
                    f'ON "service_requests" ({postgresql_columns})'
                ))
        return
    for name, table, columns in _INDEXES:
        op.create_index(name, table, list(columns), unique=False)
    for name, _postgresql_columns, sqlite_columns in _SERVICE_REQUEST_INDEXES:
        op.execute(sa.text(
            f'CREATE INDEX IF NOT EXISTS "{name}" '
            f'ON "service_requests" ({sqlite_columns})'
        ))


def upgrade() -> None:
    bind = op.get_bind()
    _backfill_session_expiry(bind)
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "expires_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )
    _backfill_service_request_created_at()
    with op.batch_alter_table("service_requests", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )
    _create_indexes(bind)


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
