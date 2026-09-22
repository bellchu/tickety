"""Add source-backed business requirement workspaces.

Revision ID: 0041
Revises: 0040
"""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    expected = {
        "requirement_workspaces": {"id", "owner_id", "title", "objective", "request_type", "created_at"},
        "requirement_sources": {"id", "workspace_id", "title", "kind", "content", "content_sha256", "created_at"},
        "business_requirements": {"id", "workspace_id", "source_id", "number", "title", "actor", "action", "benefit", "evidence_quote", "acceptance_json", "priority", "status", "revision", "validated_by", "validated_at", "reviewer_role", "validation_note", "story_json", "created_at", "updated_at"},
    }
    inspector = sa.inspect(op.get_bind())
    present = set(inspector.get_table_names()).intersection(expected)
    if present:
        # Adopt only the complete forward schema made by historical demo bootstrap.
        if present != set(expected) or any(
            {column["name"] for column in inspector.get_columns(table)} != columns
            for table, columns in expected.items()
        ):
            raise RuntimeError("Requirement schema is partially bootstrapped; apply a forward repair")
        if not any(set(item["column_names"]) == {"workspace_id", "number"}
                   for item in inspector.get_unique_constraints("business_requirements")):
            raise RuntimeError("Requirement schema lacks unique traceability numbers")
        return
    op.create_table(
        "requirement_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_requirement_workspaces_owner_id", "requirement_workspaces", ["owner_id"])
    op.create_table(
        "requirement_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("requirement_workspaces.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_requirement_sources_workspace_id", "requirement_sources", ["workspace_id"])
    op.create_table(
        "business_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("requirement_workspaces.id"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("requirement_sources.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("benefit", sa.Text(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("acceptance_json", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("validated_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("validated_at", sa.DateTime()),
        sa.Column("reviewer_role", sa.String(40)),
        sa.Column("validation_note", sa.Text()),
        sa.Column("story_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "number", name="uq_business_requirement_number"),
    )
    op.create_index("ix_business_requirements_workspace_id", "business_requirements", ["workspace_id"])


def downgrade():
    raise RuntimeError("Forward-only migration: restore a verified backup or apply a forward fix.")
