"""Repair the active-provider fence in the resolved PostgreSQL schema.

Revision ID: 0061
Revises: 0060
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels = None
depends_on = None


_TABLE = "integration_bindings"
_INDEX = "ix_integration_bindings_one_active_provider"
_PREDICATE = sa.text("state = 'active'")
_PROVIDER_EXPRESSION = sa.text("lower(trim(provider))")


def _normalized(value) -> str:
    normalized = "".join(str(value or "").lower().split()).replace('"', "").replace(
        "::character varying", ""
    ).replace("::text", "").replace("(", "").replace(")", "")
    # PostgreSQL's deparser may render SQL's ``trim(column)`` as either
    # ``TRIM(BOTH FROM column)`` or its internal ``btrim(column)`` function.
    # Both are exactly the expression installed below; normalize only those
    # spelling differences, not arbitrary expression shapes.
    return normalized.replace("trimbothfrom", "trim").replace("btrim", "trim")


def _target_index(bind):
    """Inspect only the index belonging to the relation this session resolves.

    Earlier migrations matched ``pg_class.relname`` alone.  PostgreSQL permits
    the same table and index names in different schemas, so that lookup could
    incorrectly adopt a shadow schema's index.  ``to_regclass`` follows the
    session search path exactly as the unqualified application table does.
    """
    return bind.execute(sa.text("""
        SELECT idx.indisunique AS is_unique,
               idx.indnkeyatts AS key_count,
               pg_get_expr(idx.indexprs, idx.indrelid) AS expression,
               pg_get_expr(idx.indpred, idx.indrelid) AS predicate
        FROM pg_index AS idx
        JOIN pg_class AS index_class ON index_class.oid = idx.indexrelid
        WHERE idx.indrelid = to_regclass(:table_name)
          AND index_class.relname = :index_name
    """), {"table_name": _TABLE, "index_name": _INDEX}).mappings().first()


def _target_schema(bind) -> str:
    schema = bind.execute(sa.text("""
        SELECT namespace.nspname
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE relation.oid = to_regclass(:table_name)
    """), {"table_name": _TABLE}).scalar()
    if not schema:
        raise RuntimeError("integration bindings are missing; restore a verified backup")
    return str(schema)


def _is_canonical(index) -> bool:
    return bool(
        index
        and index["is_unique"]
        and index["key_count"] == 1
        and _normalized(index["expression"]) == "lowertrimprovider"
        and _normalized(index["predicate"]) == "state='active'"
    )


def _validate_and_normalize_legacy_data(bind) -> None:
    invalid = bind.execute(sa.text("""
        SELECT 1 FROM integration_bindings
        WHERE provider IS NULL OR trim(provider) = ''
        LIMIT 1
    """)).scalar()
    if invalid is not None:
        raise RuntimeError(
            "integration binding provider is empty; repair the legacy binding before upgrading"
        )
    duplicate = bind.execute(sa.text("""
        SELECT lower(trim(provider)) FROM integration_bindings
        WHERE state = 'active'
        GROUP BY lower(trim(provider))
        HAVING COUNT(*) > 1
        LIMIT 1
    """)).scalar()
    if duplicate is not None:
        raise RuntimeError(
            "multiple active integration bindings exist for one canonical provider; "
            "suspend the unintended binding before upgrading"
        )
    bind.execute(sa.text("""
        UPDATE integration_bindings
        SET provider = lower(trim(provider))
        WHERE provider <> lower(trim(provider))
    """))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    schema = _target_schema(bind)
    existing = _target_index(bind)
    if _is_canonical(existing):
        return

    _validate_and_normalize_legacy_data(bind)
    if existing:
        op.drop_index(_INDEX, table_name=_TABLE, schema=schema)
    op.create_index(
        _INDEX,
        _TABLE,
        [_PROVIDER_EXPRESSION],
        unique=True,
        schema=schema,
        postgresql_where=_PREDICATE,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Integration binding activation is forward-only; restore a verified backup or apply a forward fix."
    )
