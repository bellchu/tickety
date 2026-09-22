"""Index requirement history in stable revision order and enforce one event per revision."""
from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    indexes = {item["name"]: item for item in sa.inspect(op.get_bind()).get_indexes("requirement_history")}
    existing = indexes.get("uq_requirement_history_revision")
    if existing:
        if existing["column_names"] != ["requirement_id", "revision"] or not existing["unique"]:
            raise RuntimeError("Requirement history index does not enforce unique revision order")
    else:
        op.create_index("uq_requirement_history_revision", "requirement_history", ["requirement_id", "revision"], unique=True)
    if "ix_requirement_history_requirement_id" in indexes:
        op.drop_index("ix_requirement_history_requirement_id", table_name="requirement_history")


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
