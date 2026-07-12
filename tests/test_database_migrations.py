import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.backend import database
from app.backend.database import Base


ROOT = Path(__file__).resolve().parents[1]


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "migration-test.db"
        self.url = f"sqlite:///{self.database_path}"
        self.config = Config(str(ROOT / "alembic.ini"))
        self.config.set_main_option("sqlalchemy.url", self.url)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": self.url})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.tempdir.cleanup()

    def _current_revision(self, engine):
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_fresh_database_upgrades_to_head_without_metadata_drift(self):
        command.upgrade(self.config, "head")
        engine = create_engine(self.url)
        try:
            inspector = inspect(engine)
            self.assertEqual(set(inspector.get_table_names()), set(Base.metadata.tables) | {"alembic_version"})
            for table_name, table in Base.metadata.tables.items():
                actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
                self.assertEqual(actual_columns, set(table.columns.keys()), table_name)
            self.assertEqual(self._current_revision(engine), "0004")
            command.check(self.config)
        finally:
            engine.dispose()

    def test_unversioned_baseline_schema_upgrades_in_place_and_preserves_data(self):
        command.upgrade(self.config, "0001")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO users (id, name) VALUES ('legacy-user', 'Legacy User')"))
                connection.execute(text(
                    "INSERT INTO tickets (id, subject, reporter) "
                    "VALUES ('legacy-ticket', 'Preserve me', 'requester@example.com')"
                ))
                connection.execute(text("DROP TABLE alembic_version"))

            command.upgrade(self.config, "head")

            inspector = inspect(engine)
            ticket_columns = {column["name"] for column in inspector.get_columns("tickets")}
            self.assertIn("portal_access_token_hash", ticket_columns)
            self.assertIn("portal_access_expires_at", ticket_columns)
            indexes = {index["name"]: index for index in inspector.get_indexes("tickets")}
            self.assertTrue(indexes["ix_tickets_portal_access_token_hash"]["unique"])
            with engine.connect() as connection:
                ticket = connection.execute(text(
                    "SELECT subject, ticket_type, workflow_status FROM tickets "
                    "WHERE id = 'legacy-ticket'"
                )).mappings().one()
                user = connection.execute(text(
                    "SELECT name, role, is_active FROM users WHERE id = 'legacy-user'"
                )).mappings().one()
            self.assertEqual(ticket["subject"], "Preserve me")
            self.assertEqual(ticket["ticket_type"], "incident")
            self.assertEqual(ticket["workflow_status"], "New")
            self.assertEqual(user["name"], "Legacy User")
            self.assertEqual(user["role"], "agent")
            self.assertTrue(user["is_active"])
            self.assertEqual(self._current_revision(engine), "0004")
        finally:
            engine.dispose()

    def test_existing_ai_artifacts_are_classified_as_legacy_stale(self):
        command.upgrade(self.config, "0002")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO tickets (id, subject, ai_reasoning, summary, recommended_solution) "
                    "VALUES ('legacy-ai', 'Old analysis', 'old reasoning', 'old summary', '{}')"
                ))
            command.upgrade(self.config, "head")
            with engine.connect() as connection:
                row = connection.execute(text(
                    "SELECT ai_status, ai_error, ai_source_hash FROM tickets WHERE id = 'legacy-ai'"
                )).mappings().one()
            self.assertEqual(row["ai_status"], "legacy_stale")
            self.assertEqual(row["ai_error"], "provenance_unknown")
            self.assertIsNone(row["ai_source_hash"])
        finally:
            engine.dispose()

    def test_production_startup_verifies_only_and_never_bootstraps(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "production"}),
            patch.object(database, "verify_database_schema") as verify,
            patch.object(database.Base.metadata, "create_all") as create_all,
            patch.object(database, "_ensure_columns") as ensure_columns,
            patch.object(database, "_ensure_ticket_search_documents") as ensure_vectors,
        ):
            database.init_db()

        verify.assert_called_once_with()
        create_all.assert_not_called()
        ensure_columns.assert_not_called()
        ensure_vectors.assert_not_called()

    def test_demo_startup_can_bootstrap_without_alembic(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "demo"}),
            patch.object(database, "verify_database_schema") as verify,
            patch.object(database.Base.metadata, "create_all") as create_all,
            patch.object(database, "_ensure_columns") as ensure_columns,
            patch.object(database, "_ensure_ticket_search_documents") as ensure_vectors,
        ):
            database.init_db()

        verify.assert_not_called()
        create_all.assert_called_once_with(bind=database.engine)
        ensure_columns.assert_called_once_with()
        ensure_vectors.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
