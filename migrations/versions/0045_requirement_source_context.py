"""Record reversible human review of supporting source context."""
from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("requirement_sources")}
    for name, kind in (("context_reviewed_at", sa.DateTime()), ("context_reviewed_by", sa.String())):
        if name not in existing:
            op.add_column("requirement_sources", sa.Column(name, kind, nullable=True))
            continue
        column = existing[name]
        if (not column["nullable"] or not isinstance(column["type"], type(kind))
                or (isinstance(kind, sa.String) and column["type"].length != kind.length)):
            raise RuntimeError("Source context review column is incompatible; apply a forward repair")


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
