"""Remove legacy Freshservice write scopes from persisted settings.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REQUIRED_SCOPE = "freshservice.tickets.view"
_ALLOWED_SCOPES = (
    _REQUIRED_SCOPE,
    "freshservice.agents.manage",
)


def upgrade() -> None:
    settings = sa.table(
        "settings",
        sa.column("key", sa.String()),
        sa.column("value", sa.Text()),
    )
    bind = op.get_bind()
    persisted = bind.execute(
        sa.select(settings.c.value).where(
            settings.c.key == "FRESHSERVICE_OAUTH_SCOPES"
        )
    ).scalar_one_or_none()
    if persisted is None:
        return

    configured = set(str(persisted or "").split())
    normalized = [scope for scope in _ALLOWED_SCOPES if scope in configured]
    if _REQUIRED_SCOPE not in normalized:
        normalized.insert(0, _REQUIRED_SCOPE)
    safe_value = " ".join(normalized)
    if safe_value != persisted:
        bind.execute(
            sa.update(settings)
            .where(settings.c.key == "FRESHSERVICE_OAUTH_SCOPES")
            .values(value=safe_value)
        )


def downgrade() -> None:
    raise RuntimeError(
        "Tickety migrations are forward-only; restore a verified backup or apply a forward fix."
    )
