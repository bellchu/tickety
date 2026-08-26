from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.backend.database import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata

# Revision 0008 owns these PostgreSQL/pgvector relations through explicit SQL
# because several columns and indexes use extension-specific types and
# expressions that the cross-dialect ORM metadata cannot safely create on
# SQLite. Excluding only reflected, database-only tables in this fixed allowlist
# prevents `alembic check` from proposing destructive drops for those
# migration-owned relations. If a future ORM model adopts one of these names,
# `compare_to` becomes non-null and ordinary drift detection resumes.
RAW_MIGRATION_MANAGED_TABLES = frozenset({
    "rag_context_snapshots_v2",
    "rag_corpus_generations_v2",
    "rag_query_embedding_cache_v2",
    "rag_v2_schema_meta",
    "ticket_search_chunks_v2",
    "ticket_search_documents",
})


def include_object(object_, name, type_, reflected, compare_to):
    if (
        type_ == "table"
        and reflected
        and compare_to is None
        and name in RAW_MIGRATION_MANAGED_TABLES
    ):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
