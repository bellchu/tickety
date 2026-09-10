"""Keep AI category output separate from canonical human ticket state.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("tickets")}
    if "ai_suggested_category" not in columns:
        op.add_column(
            "tickets",
            sa.Column("ai_suggested_category", sa.String(), nullable=True),
        )
    # The prior pipeline unconditionally wrote its classification into the
    # canonical category. Move only rows with concrete AI-generation timing
    # and no later human category audit; ambiguous legacy/imported categories
    # remain untouched rather than risking destructive misclassification.
    op.get_bind().execute(sa.text(
        """
        UPDATE tickets
        SET ai_suggested_category = category,
            category = NULL
        WHERE category IS NOT NULL
          AND ai_reasoning IS NOT NULL
          AND ai_generated_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM ticket_audit_log AS audit
              WHERE audit.ticket_id = tickets.id
                AND audit.field = 'category'
                AND audit.changed_at >= tickets.ai_generated_at
          )
        """
    ))
    if (
        op.get_bind().dialect.name == "postgresql"
        and inspector.has_table("ticket_search_documents")
    ):
        op.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS ix_ticket_search_documents_fts "
            "ON ticket_search_documents USING GIN ("
            "to_tsvector('simple'::regconfig, "
            "COALESCE(title, '') || ' ' || LEFT(COALESCE(body, ''), 20000))"
            ")"
        ))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
