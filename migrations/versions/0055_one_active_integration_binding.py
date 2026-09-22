"""Enforce the single authoritative active binding per provider."""

from alembic import op
import sqlalchemy as sa


revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


_TABLE = "integration_bindings"
_INDEX = "ix_integration_bindings_one_active_provider"
_PREDICATE = sa.text("state = 'active'")


def _canonical_index_exists(bind) -> bool:
    """Adopt the current ORM bootstrap fence when migrations run afterwards."""
    if bind.dialect.name == "sqlite":
        sql = bind.execute(sa.text(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"
        ), {"name": _INDEX}).scalar()
        normalized = "".join(str(sql or "").lower().split()).replace('"', "")
        return (
            "uniqueindex" in normalized
            and "onintegration_bindings(lower(trim(provider)))" in normalized
            and "wherestate='active'" in normalized
        )
    if bind.dialect.name == "postgresql":
        row = bind.execute(sa.text(
            "SELECT idx.indisunique AS is_unique, idx.indnkeyatts AS key_count, "
            "pg_get_expr(idx.indexprs, idx.indrelid) AS expression, "
            "pg_get_expr(idx.indpred, idx.indrelid) AS predicate "
            "FROM pg_index AS idx "
            "JOIN pg_class AS cls ON cls.oid = idx.indexrelid "
            "JOIN pg_class AS tbl ON tbl.oid = idx.indrelid "
            "WHERE cls.relname = :name AND tbl.relname = :table"
        ), {"name": _INDEX, "table": _TABLE}).mappings().first()
        normalize = lambda value: "".join(str(value or "").lower().split()).replace(
            "::character varying", ""
        ).replace("::text", "").replace("(", "").replace(")", "")
        return bool(
            row
            and row["is_unique"]
            and row["key_count"] == 1
            and normalize(row["expression"]) == "lowertrimprovider"
            and normalize(row["predicate"]) == "state='active'"
        )
    return False


def _existing_index_is_compatible(bind) -> bool:
    """Accept only the current ORM-created partial unique index on bootstrap DBs."""
    if bind.dialect.name == "sqlite":
        predicate = bind.execute(sa.text(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"
        ), {"name": _INDEX}).scalar()
    elif bind.dialect.name == "postgresql":
        predicate = bind.execute(sa.text(
            "SELECT pg_get_expr(idx.indpred, idx.indrelid) "
            "FROM pg_index AS idx "
            "JOIN pg_class AS cls ON cls.oid = idx.indexrelid "
            "JOIN pg_class AS tbl ON tbl.oid = idx.indrelid "
            "WHERE cls.relname = :name AND tbl.relname = :table"
        ), {"name": _INDEX, "table": _TABLE}).scalar()
    else:
        return False
    normalized = "".join(str(predicate or "").lower().split()).replace('"', "")
    if bind.dialect.name == "sqlite":
        return (
            normalized.startswith("createuniqueindex")
            and "onintegration_bindings(provider)" in normalized
            and "wherestate='active'" in normalized
        )
    # PostgreSQL renders VARCHAR predicates with harmless casts and parentheses.
    normalized = normalized.replace("::character varying", "").replace("::text", "")
    return normalized.replace("(", "").replace(")", "") == "state='active'"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError("integration bindings are missing; restore a verified backup")

    duplicate = bind.execute(sa.text(
        "SELECT provider FROM integration_bindings WHERE state = 'active' "
        "GROUP BY provider HAVING COUNT(*) > 1 LIMIT 1"
    )).scalar()
    if duplicate is not None:
        raise RuntimeError(
            "multiple active integration bindings exist for one provider; "
            "suspend the unintended binding before upgrading"
        )

    indexes = {index["name"]: index for index in inspector.get_indexes(_TABLE)}
    existing = indexes.get(_INDEX)
    # SQLAlchemy versions differ on whether expression indexes appear in
    # ``get_indexes``.  Check the current canonical bootstrap representation
    # first so either reflection behavior reaches 0057 safely.
    if _canonical_index_exists(bind):
        return
    if existing is not None:
        if not existing.get("unique") or not _existing_index_is_compatible(bind):
            raise RuntimeError("active integration binding index is incompatible; apply a forward repair")
        return

    op.create_index(
        _INDEX,
        _TABLE,
        ["provider"],
        unique=True,
        postgresql_where=_PREDICATE,
        sqlite_where=_PREDICATE,
    )


def downgrade():
    raise RuntimeError(
        "Integration binding activation is forward-only; restore a verified backup or apply a forward fix."
    )
