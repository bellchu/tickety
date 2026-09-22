"""Persist business questions and their accountable resolution."""
from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    expected = {"id", "workspace_id", "requirement_id", "question", "owner_role", "blocking", "status", "resolution", "created_by", "resolved_by", "created_at", "resolved_at"}
    if "requirement_decisions" in inspector.get_table_names():
        if {c["name"] for c in inspector.get_columns("requirement_decisions")} != expected:
            raise RuntimeError("Decision schema is partially bootstrapped; apply a forward repair")
        return
    op.create_table(
        "requirement_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("requirement_workspaces.id"), nullable=False),
        sa.Column("requirement_id", sa.String(36), sa.ForeignKey("business_requirements.id")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("owner_role", sa.String(200), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolution", sa.Text()),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolved_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime()),
    )
    op.create_index("ix_requirement_decisions_workspace_id", "requirement_decisions", ["workspace_id"])


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
