"""Index bounded inactive-artifact retention cleanup."""
from alembic import op
import sqlalchemy as sa


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


_INDEX_NAME = "ix_ai_artifact_records_active_created_at_id"
_INDEX_COLUMNS = ["active", "created_at", "id"]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"]: item for item in inspector.get_indexes("ai_artifact_records")}
    existing = indexes.get(_INDEX_NAME)
    if existing:
        if existing.get("column_names") != _INDEX_COLUMNS:
            raise RuntimeError("AI artifact retention index is incompatible; apply a forward repair")
        return
    op.create_index(_INDEX_NAME, "ai_artifact_records", _INDEX_COLUMNS, unique=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if _INDEX_NAME in {item["name"] for item in inspector.get_indexes("ai_artifact_records")}:
        op.drop_index(_INDEX_NAME, table_name="ai_artifact_records")
