"""Normalize legacy asset lifecycle statuses.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_MAP = {
    "Active": "In Use",
    "In Repair": "Broken",
    "Lost/Stolen": "Lost",
}
_CANONICAL_STATUSES = {"In Use", "Available", "Retired", "Broken", "Lost"}
_AMBIGUOUS_STATUSES = {"Inactive"}


def upgrade() -> None:
    bind = op.get_bind()
    existing = {
        row[0]
        for row in bind.execute(sa.text("SELECT DISTINCT status FROM assets"))
    }
    ambiguous = existing & _AMBIGUOUS_STATUSES
    if ambiguous:
        raise RuntimeError(
            "Cannot guess whether legacy asset status 'Inactive' means "
            "'Available' or 'Retired'; classify those rows explicitly before upgrading"
        )
    unexpected = existing - _CANONICAL_STATUSES - set(_STATUS_MAP)
    unexpected -= _AMBIGUOUS_STATUSES
    if unexpected:
        rendered = ", ".join(
            "NULL" if value is None else repr(value)
            for value in sorted(unexpected, key=lambda value: "" if value is None else str(value))
        )
        raise RuntimeError(
            "Cannot normalize assets with unknown lifecycle statuses: " + rendered
        )

    for old_status, new_status in _STATUS_MAP.items():
        bind.execute(
            sa.text(
                "UPDATE assets SET status = :new_status WHERE status = :old_status"
            ),
            {"old_status": old_status, "new_status": new_status},
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
