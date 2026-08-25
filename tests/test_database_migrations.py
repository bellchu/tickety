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
            self.assertEqual(self._current_revision(engine), "0021")
            self.assertIn("external_users", inspector.get_table_names())
            self.assertIn("external_conversations", inspector.get_table_names())
            self.assertIn("external_activity_ledger", inspector.get_table_names())
            self.assertIn("external_ticket_context", inspector.get_table_names())
            self.assertIn("sso_identities", inspector.get_table_names())
            self.assertIn("sso_transactions", inspector.get_table_names())
            self.assertIn("external_groups", inspector.get_table_names())
            self.assertIn("external_group_memberships", inspector.get_table_names())
            self.assertIn("user_external_identity_links", inspector.get_table_names())
            self.assertIn("agent_ticket_state", inspector.get_table_names())
            self.assertIn("intelligence_studies", inspector.get_table_names())
            self.assertNotIn("user_mappings", inspector.get_table_names())
            session_columns = {
                column["name"]
                for column in inspector.get_columns("integration_sessions")
            }
            self.assertNotIn("user_id", session_columns)
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
            self.assertIn("ai_suggested_category", ticket_columns)
            self.assertIn("binding_id", ticket_columns)
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
            self.assertEqual(self._current_revision(engine), "0021")
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

    def test_ai_dispatch_recovery_cancels_terminal_work_and_keeps_telemetry(self):
        command.upgrade(self.config, "0018")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO tickets "
                    "(id, subject, status, ai_status, ai_requested_artifacts, ai_attempts) "
                    "VALUES ('closed-ai', 'Historical', 'Closed', 'queued', 'triage', 2)"
                ))
                connection.execute(text(
                    "INSERT INTO llm_provider_cooldowns "
                    "(provider, reason, retry_at, updated_at) VALUES "
                    "('foundry', 'provider_capacity', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ))
                connection.execute(text(
                    "INSERT INTO llm_call_records "
                    "(provider, model, task, status, attempts, latency_ms, "
                    "prompt_tokens, completion_tokens, total_tokens, synthetic, created_at) "
                    "VALUES ('foundry', 'deployment', 'TriageAnalysis', 'success', 1, 10, "
                    "1, 1, 2, 0, CURRENT_TIMESTAMP)"
                ))

            command.upgrade(self.config, "head")
            with engine.connect() as connection:
                ticket = connection.execute(text(
                    "SELECT ai_status, ai_error, ai_requested_artifacts, ai_attempts "
                    "FROM tickets WHERE id = 'closed-ai'"
                )).mappings().one()
                cooldowns = connection.execute(text(
                    "SELECT COUNT(*) FROM llm_provider_cooldowns"
                )).scalar_one()
                call = connection.execute(text(
                    "SELECT dispatched, estimated_tokens FROM llm_call_records"
                )).mappings().one()
            self.assertEqual(ticket["ai_status"], "not_applicable")
            self.assertEqual(ticket["ai_error"], "terminal_ticket")
            self.assertIsNone(ticket["ai_requested_artifacts"])
            self.assertEqual(ticket["ai_attempts"], 0)
            self.assertEqual(cooldowns, 0)
            self.assertFalse(call["dispatched"])
            self.assertEqual(call["estimated_tokens"], 0)
        finally:
            engine.dispose()

    def test_proven_ai_category_is_moved_but_later_human_category_is_preserved(self):
        command.upgrade(self.config, "0004")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO tickets "
                    "(id, subject, category, ai_reasoning, ai_generated_at) VALUES "
                    "('ai-category', 'AI classified', 'Software', 'reason', "
                    "'2026-07-12 10:00:00'), "
                    "('human-category', 'Human corrected', 'Network', 'reason', "
                    "'2026-07-12 10:00:00')"
                ))
                connection.execute(text(
                    "INSERT INTO ticket_audit_log "
                    "(ticket_id, field, old_value, new_value, changed_by, changed_at) "
                    "VALUES ('human-category', 'category', 'Software', 'Network', "
                    "'Reviewer', '2026-07-12 11:00:00')"
                ))

            command.upgrade(self.config, "head")
            with engine.connect() as connection:
                rows = {
                    row["id"]: row
                    for row in connection.execute(text(
                        "SELECT id, category, ai_suggested_category FROM tickets "
                        "WHERE id IN ('ai-category', 'human-category')"
                    )).mappings()
                }
            self.assertIsNone(rows["ai-category"]["category"])
            self.assertEqual(
                rows["ai-category"]["ai_suggested_category"], "Software"
            )
            self.assertEqual(rows["human-category"]["category"], "Network")
            self.assertIsNone(rows["human-category"]["ai_suggested_category"])
        finally:
            engine.dispose()

    def test_read_only_scope_migration_removes_legacy_write_permissions(self):
        command.upgrade(self.config, "0009")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO settings (key, value) VALUES "
                    "('FRESHSERVICE_OAUTH_SCOPES', "
                    "'freshservice.tickets.view freshservice.tickets.edit "
                    "freshservice.agents.manage')"
                ))

            command.upgrade(self.config, "head")

            with engine.connect() as connection:
                scopes = connection.execute(text(
                    "SELECT value FROM settings "
                    "WHERE key = 'FRESHSERVICE_OAUTH_SCOPES'"
                )).scalar_one()
            self.assertEqual(
                scopes,
                "freshservice.tickets.view freshservice.agents.manage",
            )
            self.assertEqual(self._current_revision(engine), "0021")
        finally:
            engine.dispose()

    def test_read_only_scope_migration_fails_closed_for_unknown_scopes(self):
        command.upgrade(self.config, "0009")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO settings (key, value) VALUES "
                    "('FRESHSERVICE_OAUTH_SCOPES', "
                    "'freshservice.tickets.edit freshservice.assets.view')"
                ))

            command.upgrade(self.config, "head")

            with engine.connect() as connection:
                scopes = connection.execute(text(
                    "SELECT value FROM settings "
                    "WHERE key = 'FRESHSERVICE_OAUTH_SCOPES'"
                )).scalar_one()
            self.assertEqual(scopes, "freshservice.tickets.view")
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

    def test_blank_app_mode_uses_production_verification_path(self):
        with (
            patch.dict(os.environ, {"APP_MODE": ""}),
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
