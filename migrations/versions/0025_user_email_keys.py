"""Enforce one canonical email identity per Tickety user.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _canonical_email(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # The previous application revision can still be serving while the
        # Compose migration container starts. Lock before taking the identity
        # snapshot so a concurrent insert cannot commit after the SELECT and
        # escape with a NULL key once this revision is stamped complete.
        connection.execute(sa.text("LOCK TABLE users IN ACCESS EXCLUSIVE MODE"))
    rows = connection.execute(sa.text("SELECT id, email FROM users")).all()
    updates: list[dict[str, str | None]] = []
    owner_by_key: dict[str, str] = {}
    for user_id, email in rows:
        email_key = _canonical_email(email)
        if email_key is not None:
            if "\x00" in email_key or len(email_key) > 320:
                raise RuntimeError(
                    "users contains an invalid canonical email; resolve it before migration 0025"
                )
            previous_owner = owner_by_key.get(email_key)
            if previous_owner is not None and previous_owner != user_id:
                raise RuntimeError(
                    "users contains duplicate canonical emails; resolve them before migration 0025"
                )
            owner_by_key[email_key] = user_id
        updates.append({"user_id": user_id, "email": email_key, "email_key": email_key})

    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("users")}
    unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("users")
    }
    check_names = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("users")
    }
    unique_names.update({index.get("name") for index in inspector.get_indexes("users")})
    with op.batch_alter_table("users", schema=None) as batch_op:
        if "email_key" not in columns:
            batch_op.add_column(sa.Column("email_key", sa.String(length=320), nullable=True))
        if "uix_users_email_key" not in unique_names:
            batch_op.create_unique_constraint("uix_users_email_key", ["email_key"])

    if updates:
        connection.execute(sa.text(
            "UPDATE users SET email = :email, email_key = :email_key WHERE id = :user_id"
        ), updates)

    if "ck_users_email_identity_canonical" not in check_names:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.create_check_constraint(
                "ck_users_email_identity_canonical",
                "(email IS NULL AND email_key IS NULL) OR "
                "(email IS NOT NULL AND email_key IS NOT NULL AND "
                "email = lower(trim(email)) AND email_key = email)",
            )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
