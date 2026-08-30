"""Add binding-scoped Freshservice trial integration foundations.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def _unique_constraint_name(
    table_name: str,
    columns: tuple[str, ...],
    *,
    preferred_name: str,
) -> str:
    """Resolve a historical unique constraint without guessing its DB name."""
    expected_columns = set(columns)
    matches = [
        constraint
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
        if set(constraint.get("column_names") or ()) == expected_columns
    ]
    preferred = [
        constraint for constraint in matches
        if constraint.get("name") == preferred_name
    ]
    if len(preferred) == 1:
        return preferred_name
    named = [constraint.get("name") for constraint in matches if constraint.get("name")]
    if len(named) == 1:
        return str(named[0])
    if len(matches) == 1 and not matches[0].get("name"):
        # SQLite often reflects unnamed unique constraints. Alembic's batch
        # naming convention assigns the deterministic preferred name.
        return preferred_name
    raise RuntimeError(
        f"Expected exactly one unique constraint on {table_name}{columns}; "
        f"found {len(matches)}"
    )


def upgrade() -> None:
    op.create_table(
        "integration_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("canonical_account_host", sa.String(length=255), nullable=False),
        sa.Column("installation_id", sa.String(length=255), nullable=True),
        sa.Column("workspace_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("product_variant", sa.String(length=32), nullable=True),
        sa.Column(
            "credential_reference",
            sa.String(length=255),
            nullable=False,
            server_default="env://freshservice",
        ),
        sa.Column("capability_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("validation_evidence", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("activated_by", sa.String(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "environment",
            "canonical_account_host",
            "installation_id",
            name="uix_integration_binding_installation",
        ),
    )
    op.create_index("ix_integration_bindings_provider", "integration_bindings", ["provider"])
    op.create_index("ix_integration_bindings_environment", "integration_bindings", ["environment"])
    op.create_index("ix_integration_bindings_state", "integration_bindings", ["state"])
    op.create_index("ix_integration_bindings_expires_at", "integration_bindings", ["expires_at"])
    op.create_index(
        "ix_integration_binding_lookup",
        "integration_bindings",
        ["provider", "environment", "state"],
    )

    op.create_table(
        "integration_capabilities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_bindings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "capability", name="uix_binding_capability"),
    )
    op.create_index("ix_integration_capabilities_binding_id", "integration_capabilities", ["binding_id"])

    op.create_table(
        "integration_bootstrap_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=True),
        sa.Column("workspace_id", sa.String(length=255), nullable=True),
        sa.Column("audience", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_bindings.id"]),
        sa.PrimaryKeyConstraint("code_hash"),
    )
    op.create_index("ix_integration_bootstrap_codes_binding_id", "integration_bootstrap_codes", ["binding_id"])
    op.create_index("ix_integration_bootstrap_codes_expires_at", "integration_bootstrap_codes", ["expires_at"])

    op.create_table(
        "integration_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_bindings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_audit_log_binding_id", "integration_audit_log", ["binding_id"])
    op.create_index("ix_integration_audit_log_action", "integration_audit_log", ["action"])
    op.create_index("ix_integration_audit_log_created_at", "integration_audit_log", ["created_at"])

    op.create_table(
        "provider_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=True),
        sa.Column("operation", sa.String(length=96), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("expected_external_version", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("response_reference", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_bindings.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "idempotency_key", name="uix_binding_idempotency_key"),
    )
    op.create_index("ix_provider_operations_binding_id", "provider_operations", ["binding_id"])
    op.create_index("ix_provider_operations_ticket_id", "provider_operations", ["ticket_id"])
    op.create_index("ix_provider_operations_status", "provider_operations", ["status"])

    op.create_table(
        "provider_conflicts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=True),
        sa.Column("field", sa.String(length=96), nullable=False),
        sa.Column("provider_snapshot", sa.Text(), nullable=False),
        sa.Column("tickety_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_bindings.id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["provider_operations.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_conflicts_operation_id", "provider_conflicts", ["operation_id"])
    op.create_index("ix_provider_conflicts_binding_id", "provider_conflicts", ["binding_id"])
    op.create_index("ix_provider_conflicts_ticket_id", "provider_conflicts", ["ticket_id"])
    op.create_index("ix_provider_conflicts_status", "provider_conflicts", ["status"])

    tickets_external_unique = _unique_constraint_name(
        "tickets",
        ("external_source", "external_id"),
        preferred_name="uix_external_ticket",
    )
    with op.batch_alter_table("tickets", naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.add_column(
            sa.Column("binding_id", sa.String(length=36), nullable=False, server_default="legacy")
        )
        batch_op.drop_constraint(tickets_external_unique, type_="unique")
        batch_op.create_unique_constraint(
            "uix_binding_external_ticket",
            ["binding_id", "external_source", "external_id"],
        )
        batch_op.create_index("ix_tickets_binding_id", ["binding_id"], unique=False)

    assignee_external_unique = _unique_constraint_name(
        "user_mappings",
        ("external_source", "external_assignee_id"),
        preferred_name="uix_external_assignee",
    )
    with op.batch_alter_table("user_mappings", naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.add_column(
            sa.Column("binding_id", sa.String(length=36), nullable=False, server_default="legacy")
        )
        batch_op.drop_constraint(assignee_external_unique, type_="unique")
        batch_op.create_unique_constraint(
            "uix_binding_external_assignee",
            ["binding_id", "external_source", "external_assignee_id"],
        )
        batch_op.create_index("ix_user_mappings_binding_id", ["binding_id"], unique=False)

    sync_provider_unique = _unique_constraint_name(
        "sync_state",
        ("provider",),
        preferred_name="uq_sync_state_provider",
    )
    with op.batch_alter_table("sync_state", naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.add_column(
            sa.Column("binding_id", sa.String(length=36), nullable=False, server_default="legacy")
        )
        batch_op.drop_constraint(sync_provider_unique, type_="unique")
        batch_op.create_unique_constraint(
            "uix_sync_state_binding_provider", ["binding_id", "provider"]
        )
        batch_op.create_index("ix_sync_state_binding_id", ["binding_id"], unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
