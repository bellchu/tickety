"""Bind attachment-blob deletion idempotency to its storage target."""

from alembic import op
import sqlalchemy as sa


revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


_TABLE = "attachment_blob_deletions"
_CONSTRAINT = "uix_attachment_blob_deletion_identity"
_LEGACY_COLUMNS = ["attachment_id", "blob_key"]
_TARGET_COLUMNS = [
    "attachment_id", "blob_key", "storage_provider",
    "storage_account_identity", "storage_container",
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError("attachment blob cleanup queue is missing; restore a verified backup")
    constraints = {
        constraint["name"]: constraint
        for constraint in inspector.get_unique_constraints(_TABLE)
    }
    identity = constraints.get(_CONSTRAINT)
    if not identity:
        raise RuntimeError("attachment blob cleanup identity is incompatible; apply a forward repair")
    columns = identity.get("column_names")
    if columns == _TARGET_COLUMNS:
        return
    if columns != _LEGACY_COLUMNS:
        raise RuntimeError("attachment blob cleanup identity is incompatible; apply a forward repair")

    # SQLite needs a table rebuild for named UNIQUE constraints; Alembic's
    # batch operation preserves the queue's checks and indexes while PostgreSQL
    # uses the same audited constraint replacement through native DDL.
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CONSTRAINT, type_="unique")
        batch.create_unique_constraint(_CONSTRAINT, _TARGET_COLUMNS)


def downgrade():
    raise RuntimeError("Attachment deletion target identity is forward-only; restore a verified backup or apply a forward fix.")
