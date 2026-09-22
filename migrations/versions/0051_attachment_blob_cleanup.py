"""Durable cleanup queue for superseded private attachment blobs."""

from alembic import op
import sqlalchemy as sa


revision = "0051"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("external_attachments")}
    for name, column in (
        ("storage_provider", sa.Column("storage_provider", sa.String(length=64), nullable=True)),
        ("storage_account_identity", sa.Column("storage_account_identity", sa.String(length=255), nullable=True)),
        ("storage_container", sa.Column("storage_container", sa.String(length=63), nullable=True)),
    ):
        if name not in columns:
            op.add_column("external_attachments", column)

    table_name = "attachment_blob_deletions"
    expected_columns = {
        "id", "attachment_id", "blob_key", "storage_provider",
        "storage_account_identity", "storage_container", "status", "attempts",
        "last_error", "next_attempt_at", "lease_token", "lease_expires_at",
        "requested_at", "completed_at",
    }
    expected_indexes = {
        "ix_attachment_blob_deletions_attachment_id": ["attachment_id"],
        "ix_attachment_blob_deletions_status": ["status"],
        "ix_attachment_blob_deletions_next_attempt_at": ["next_attempt_at"],
        "ix_attachment_blob_deletions_lease_expires_at": ["lease_expires_at"],
        "ix_attachment_blob_deletions_ready": [
            "status", "next_attempt_at", "requested_at", "id",
        ],
    }
    if table_name in inspector.get_table_names():
        # Demo/bootstrap paths can create current ORM tables before Alembic is
        # stamped.  Adopt only an exact, constraint-complete representation;
        # accepting a vaguely similar queue would weaken the durable claim
        # contract and make a later remote delete unsafe.
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        if actual_columns != expected_columns:
            raise RuntimeError("attachment blob cleanup schema is incompatible; apply a forward repair")
        if inspector.get_pk_constraint(table_name).get("constrained_columns") != ["id"]:
            raise RuntimeError("attachment blob cleanup primary key is incompatible; apply a forward repair")
        constraints = {
            constraint["name"]: constraint
            for constraint in inspector.get_unique_constraints(table_name)
        }
        identity = constraints.get("uix_attachment_blob_deletion_identity")
        known_identity_shapes = {
            ("attachment_id", "blob_key"),
            (
                "attachment_id", "blob_key", "storage_provider",
                "storage_account_identity", "storage_container",
            ),
        }
        if (
            not identity
            or tuple(identity.get("column_names") or ()) not in known_identity_shapes
        ):
            raise RuntimeError("attachment blob cleanup identity is incompatible; apply a forward repair")
        checks = {
            constraint["name"]: constraint
            for constraint in inspector.get_check_constraints(table_name)
        }
        if {
            "ck_attachment_blob_deletion_status",
            "ck_attachment_blob_deletion_attempts",
        } - set(checks):
            raise RuntimeError("attachment blob cleanup checks are incompatible; apply a forward repair")
        indexes = {index["name"]: index for index in inspector.get_indexes(table_name)}
        if any(
            name not in indexes or indexes[name].get("column_names") != columns
            for name, columns in expected_indexes.items()
        ):
            raise RuntimeError("attachment blob cleanup indexes are incompatible; apply a forward repair")
        return

    op.create_table(
        table_name,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("attachment_id", sa.String(length=36), nullable=False),
        sa.Column("blob_key", sa.Text(), nullable=False),
        sa.Column("storage_provider", sa.String(length=64), nullable=False),
        sa.Column("storage_account_identity", sa.String(length=255), nullable=False),
        sa.Column("storage_container", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("attachment_id", "blob_key", name="uix_attachment_blob_deletion_identity"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'deleted', 'failed', 'cancelled')",
            name="ck_attachment_blob_deletion_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_attachment_blob_deletion_attempts"),
    )
    for name, columns in expected_indexes.items():
        op.create_index(name, table_name, columns)


def downgrade():
    raise RuntimeError("Attachment blob cleanup is forward-only; restore a verified backup or apply a forward fix.")
