"""Keep before/after evidence for requirement changes and agreement."""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    expected = {"id", "requirement_id", "actor_id", "action", "revision", "before_json", "after_json", "created_at"}
    if "requirement_history" in inspector.get_table_names():
        if {c["name"] for c in inspector.get_columns("requirement_history")} != expected:
            raise RuntimeError("Requirement history schema is incomplete; apply a forward repair")
        return
    op.create_table(
        "requirement_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requirement_id", sa.String(36), sa.ForeignKey("business_requirements.id"), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_requirement_history_requirement_id", "requirement_history", ["requirement_id"])


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
