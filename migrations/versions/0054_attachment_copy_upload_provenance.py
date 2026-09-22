"""Preserve target provenance for an upload whose result is ambiguous."""

from alembic import op
import sqlalchemy as sa


revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


_TABLE = "external_attachments"
_COLUMNS = (
    ("copy_upload_blob_key", sa.Text()),
    ("copy_upload_storage_provider", sa.String(length=64)),
    ("copy_upload_storage_account_identity", sa.String(length=255)),
    ("copy_upload_storage_container", sa.String(length=63)),
    ("copy_upload_started_at", sa.DateTime()),
)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError("external attachments are missing; restore a verified backup")
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, column_type, nullable=True))


def downgrade():
    raise RuntimeError("Attachment copy upload provenance is forward-only; restore a verified backup or apply a forward fix.")
