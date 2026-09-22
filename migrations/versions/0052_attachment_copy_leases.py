"""Fence private attachment copies with durable row-level leases."""

from alembic import op
import sqlalchemy as sa


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


_TABLE = "external_attachments"
_INDEX = "ix_external_attachments_copy_ready"
_INDEX_COLUMNS = [
    "binding_id", "provider", "storage_status", "next_attempt_at",
    "copy_lease_expires_at", "created_at", "id",
]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError("external attachments are missing; restore a verified backup")
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, column in (
        ("copy_lease_token", sa.Column("copy_lease_token", sa.String(length=36), nullable=True)),
        ("copy_lease_expires_at", sa.Column("copy_lease_expires_at", sa.DateTime(), nullable=True)),
    ):
        if name not in columns:
            op.add_column(_TABLE, column)

    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"]: index for index in inspector.get_indexes(_TABLE)}
    existing = indexes.get(_INDEX)
    if existing:
        if existing.get("column_names") != _INDEX_COLUMNS:
            raise RuntimeError("attachment copy lease index is incompatible; apply a forward repair")
        return
    op.create_index(_INDEX, _TABLE, _INDEX_COLUMNS, unique=False)


def downgrade():
    raise RuntimeError("Attachment copy leases are forward-only; restore a verified backup or apply a forward fix.")
