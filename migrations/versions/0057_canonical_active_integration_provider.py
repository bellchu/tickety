"""Canonicalize provider identity for the authoritative active binding."""

from alembic import op
import sqlalchemy as sa


revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


_TABLE = "integration_bindings"
_INDEX = "ix_integration_bindings_one_active_provider"
_PREDICATE = sa.text("state = 'active'")
_PROVIDER_EXPRESSION = sa.text("lower(trim(provider))")


def _index_sql(bind) -> str:
    if bind.dialect.name == "sqlite":
        value = bind.execute(sa.text(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"
        ), {"name": _INDEX}).scalar()
    elif bind.dialect.name == "postgresql":
        return ""
    else:
        raise RuntimeError("canonical provider migration supports SQLite and PostgreSQL only")
    return "".join(str(value or "").lower().split()).replace('"', "")


def _postgres_index_parts(bind):
    """Read catalog expressions, avoiding schema-qualified index DDL parsing."""
    return bind.execute(sa.text(
        "SELECT idx.indisunique AS is_unique, idx.indnkeyatts AS key_count, "
        "pg_get_expr(idx.indexprs, idx.indrelid) AS expression, "
        "pg_get_expr(idx.indpred, idx.indrelid) AS predicate, key_attr.attname AS key_column "
        "FROM pg_index AS idx "
        "JOIN pg_class AS cls ON cls.oid = idx.indexrelid "
        "JOIN pg_class AS tbl ON tbl.oid = idx.indrelid "
        "LEFT JOIN LATERAL unnest(idx.indkey::smallint[]) WITH ORDINALITY "
        "AS key_number(attnum, ordinal) ON key_number.ordinal = 1 "
        "LEFT JOIN pg_attribute AS key_attr ON key_attr.attrelid = idx.indrelid "
        "AND key_attr.attnum = key_number.attnum "
        "WHERE cls.relname = :name AND tbl.relname = :table"
    ), {"name": _INDEX, "table": _TABLE}).mappings().first()


def _normalized(value) -> str:
    return "".join(str(value or "").lower().split()).replace('"', "").replace(
        "::character varying", ""
    ).replace("::text", "").replace("(", "").replace(")", "")


def _existing_index_is_compatible(bind) -> bool:
    if bind.dialect.name == "postgresql":
        parts = _postgres_index_parts(bind)
        return bool(
            parts
            and parts["is_unique"]
            and parts["key_count"] == 1
            and _normalized(parts["expression"]) == "lowertrimprovider"
            and _normalized(parts["predicate"]) == "state='active'"
        )
    sql = _normalized(_index_sql(bind))
    return (
        "uniqueindex" in sql or "createuniqueindex" in sql
    ) and "onintegration_bindingslowertrimprovider" in sql and "wherestate='active'" in sql


def _existing_index_is_legacy_0055(bind) -> bool:
    if bind.dialect.name == "postgresql":
        parts = _postgres_index_parts(bind)
        return bool(
            parts
            and parts["is_unique"]
            and parts["key_count"] == 1
            and parts["expression"] is None
            and parts["key_column"] == "provider"
            and _normalized(parts["predicate"]) == "state='active'"
        )
    sql = _normalized(_index_sql(bind))
    return (
        ("uniqueindex" in sql or "createuniqueindex" in sql)
        and "onintegration_bindingsprovider" in sql
        and "wherestate='active'" in sql
    )


def _named_index_state(bind) -> str:
    """Classify the named activation fence before any legacy data changes."""
    index_exists = (
        bool(_postgres_index_parts(bind))
        if bind.dialect.name == "postgresql"
        else bool(_index_sql(bind))
    )
    if not index_exists:
        return "missing"
    if _existing_index_is_compatible(bind):
        return "canonical"
    if _existing_index_is_legacy_0055(bind):
        return "legacy"
    raise RuntimeError("active integration binding index is incompatible; apply a forward repair")


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError("integration bindings are missing; restore a verified backup")

    invalid = bind.execute(sa.text(
        "SELECT 1 FROM integration_bindings "
        "WHERE provider IS NULL OR trim(provider) = '' LIMIT 1"
    )).scalar()
    if invalid is not None:
        raise RuntimeError(
            "integration binding provider is empty; repair the legacy binding before upgrading"
        )

    duplicate = bind.execute(sa.text(
        "SELECT lower(trim(provider)) FROM integration_bindings "
        "WHERE state = 'active' GROUP BY lower(trim(provider)) "
        "HAVING COUNT(*) > 1 LIMIT 1"
    )).scalar()
    if duplicate is not None:
        raise RuntimeError(
            "multiple active integration bindings exist for one canonical provider; "
            "suspend the unintended binding before upgrading"
        )

    installation_collision = bind.execute(sa.text(
        "SELECT lower(trim(provider)) FROM integration_bindings "
        "WHERE installation_id IS NOT NULL "
        "GROUP BY lower(trim(provider)), environment, canonical_account_host, installation_id "
        "HAVING COUNT(*) > 1 LIMIT 1"
    )).scalar()
    if installation_collision is not None:
        raise RuntimeError(
            "provider canonicalization would merge integration installation identities; "
            "retire or repair the ambiguous legacy binding before upgrading"
        )

    # Inspect the target fence before changing any legacy spelling.  This
    # keeps an incompatible, same-named pre-existing index a read-only
    # migration failure and makes the only replaceable form explicit.
    index_state = _named_index_state(bind)

    # Every new application write uses this exact identity.  Normalize legacy
    # spellings before replacing 0055's case-sensitive partial unique index.
    bind.execute(sa.text(
        "UPDATE integration_bindings SET provider = lower(trim(provider)) "
        "WHERE provider <> lower(trim(provider))"
    ))

    if index_state == "canonical":
        return
    if index_state == "legacy":
        op.drop_index(_INDEX, table_name=_TABLE)

    op.create_index(
        _INDEX,
        _TABLE,
        [_PROVIDER_EXPRESSION],
        unique=True,
        postgresql_where=_PREDICATE,
        sqlite_where=_PREDICATE,
    )


def downgrade():
    raise RuntimeError(
        "Integration binding activation is forward-only; restore a verified backup or apply a forward fix."
    )
