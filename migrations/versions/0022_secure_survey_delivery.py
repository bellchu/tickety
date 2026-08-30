"""Bind CSAT delivery to one-time public response capabilities.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows predate provider delivery and capability auditing. Mark
    # them legacy so they remain visible while staying ineligible for public
    # response and accepted-delivery statistics.
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    survey_columns = {
        column["name"] for column in inspector.get_columns("surveys")
    }
    survey_indexes = {
        index["name"] for index in inspector.get_indexes("surveys")
    }
    survey_unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("surveys")
    }
    survey_foreign_keys = {
        foreign_key.get("name")
        for foreign_key in inspector.get_foreign_keys("surveys")
    }
    with op.batch_alter_table("surveys", schema=None) as batch_op:
        additions = (
            sa.Column("response_token_hash", sa.String(length=64), nullable=True),
            sa.Column("active_delivery_key", sa.String(length=64), nullable=True),
            sa.Column("response_expires_at", sa.DateTime(), nullable=True),
            sa.Column("question_snapshot", sa.Text(), nullable=True),
            sa.Column("recipient_email", sa.String(length=320), nullable=True),
            sa.Column("recipient_name", sa.String(length=255), nullable=True),
            sa.Column(
                "delivery_status",
                sa.String(length=32),
                nullable=False,
                server_default="legacy",
            ),
            sa.Column("delivery_message_id", sa.String(length=255), nullable=True),
            sa.Column("delivery_error", sa.String(length=64), nullable=True),
            sa.Column("delivery_attempted_at", sa.DateTime(), nullable=True),
            sa.Column("sent_by", sa.String(), nullable=True),
        )
        for column in additions:
            if column.name not in survey_columns:
                batch_op.add_column(column)
        if "fk_surveys_sent_by_users" not in survey_foreign_keys:
            batch_op.create_foreign_key(
                "fk_surveys_sent_by_users", "users", ["sent_by"], ["id"]
            )
        for index_name, columns, unique in (
            ("ix_surveys_response_token_hash", ["response_token_hash"], True),
            ("ix_surveys_active_delivery_key", ["active_delivery_key"], True),
            ("ix_surveys_delivery_status", ["delivery_status"], False),
        ):
            if index_name not in survey_indexes | survey_unique_names:
                batch_op.create_index(index_name, columns, unique=unique)

    # The old endpoint permitted more than one row per survey under a race.
    # Preserve the earliest response deterministically before adding the
    # database-enforced one-response invariant.
    op.execute(
        sa.text(
            "DELETE FROM survey_responses "
            "WHERE id NOT IN ("
            "SELECT first_response_id FROM ("
            "SELECT MIN(id) AS first_response_id FROM survey_responses GROUP BY survey_id"
            ") AS retained_responses"
            ")"
        )
    )
    inspector = sa.inspect(connection)
    response_unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("survey_responses")
    }
    response_index_names = {
        index["name"] for index in inspector.get_indexes("survey_responses")
    }
    response_constraint = "uix_survey_response_once"
    if response_constraint not in response_unique_names:
        if (
            connection.dialect.name == "postgresql"
            and response_constraint in response_index_names
        ):
            # Demo compatibility creates the same unique index before Alembic
            # advances. Adopt it as the authoritative constraint without a
            # second table scan or a duplicate relation name.
            op.execute(sa.text(
                'ALTER TABLE survey_responses ADD CONSTRAINT '
                '"uix_survey_response_once" UNIQUE USING INDEX '
                '"uix_survey_response_once"'
            ))
        else:
            if response_constraint in response_index_names:
                op.drop_index(response_constraint, table_name="survey_responses")
            with op.batch_alter_table("survey_responses", schema=None) as batch_op:
                batch_op.create_unique_constraint(
                    response_constraint, ["survey_id"]
                )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
