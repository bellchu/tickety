"""Enforce case-insensitive ticket configuration identities.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-26
"""

from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONFIG_TABLES = (
    ("ticket_status_config", "uix_ticket_status_config_name_key", 100),
    ("ticket_priority_config", "uix_ticket_priority_config_name_key", 32),
)


def upgrade() -> None:
    connection = op.get_bind()
    # SQLite DDL is non-transactional under Alembic. Validate every table
    # before the first ALTER so an ambiguous legacy row cannot leave another
    # table half-migrated and make a corrected retry impossible.
    for table_name, _constraint_name, max_name_length in _CONFIG_TABLES:
        invalid_name = next(
            (
                name
                for name in connection.execute(
                    sa.text(f"SELECT name FROM {table_name}")
                ).scalars()
                if not isinstance(name, str)
                or name != name.strip()
                or len(name) > max_name_length
                or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9 _-]*",
                    name.strip(),
                )
            ),
            None,
        )
        if invalid_name is not None:
            raise RuntimeError(
                f"{table_name} contains surrounding whitespace, an overlong name, "
                "or a name outside the portable ASCII key format; "
                "resolve it before applying migration 0023"
            )
        duplicate = connection.execute(sa.text(
            f"SELECT lower(trim(name)) AS normalized_name FROM {table_name} "
            "GROUP BY lower(trim(name)) HAVING COUNT(*) > 1 LIMIT 1"
        )).scalar_one_or_none()
        if duplicate is not None:
            raise RuntimeError(
                f"{table_name} contains case-insensitive duplicate names; "
                "resolve them before applying migration 0023"
            )

    for table_name, constraint_name, _max_name_length in _CONFIG_TABLES:
        inspector = sa.inspect(connection)
        columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name)
        }
        if "name_key" not in columns:
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("name_key", sa.String(length=100), nullable=True)
                )

        connection.execute(sa.text(
            f"UPDATE {table_name} SET name_key = lower(trim(name))"
        ))
        inspector = sa.inspect(connection)
        columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name)
        }
        unique_names = {
            constraint.get("name")
            for constraint in inspector.get_unique_constraints(table_name)
        }
        index_names = {
            index["name"] for index in inspector.get_indexes(table_name)
        }
        has_constraint = constraint_name in unique_names
        has_compatibility_index = constraint_name in index_names

        if (
            has_compatibility_index
            and not has_constraint
            and connection.dialect.name != "postgresql"
        ):
            op.drop_index(constraint_name, table_name=table_name)
            has_compatibility_index = False

        needs_not_null = bool(columns["name_key"].get("nullable", True))
        needs_batch_constraint = not has_constraint and not has_compatibility_index
        if needs_not_null or needs_batch_constraint:
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                if needs_not_null:
                    batch_op.alter_column(
                        "name_key",
                        existing_type=sa.String(length=100),
                        nullable=False,
                    )
                if needs_batch_constraint:
                    batch_op.create_unique_constraint(
                        constraint_name, ["name_key"]
                    )

        if (
            connection.dialect.name == "postgresql"
            and has_compatibility_index
            and not has_constraint
        ):
            op.execute(sa.text(
                f'ALTER TABLE "{table_name}" ADD CONSTRAINT '
                f'"{constraint_name}" UNIQUE USING INDEX "{constraint_name}"'
            ))


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
