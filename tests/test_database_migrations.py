import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.backend import database, main
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
            self.assertEqual(self._current_revision(engine), "0033")
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
            ticket_columns = {
                column["name"] for column in inspector.get_columns("tickets")
            }
            self.assertTrue({
                "ai_suggested_team",
                "ai_secondary_team",
                "ai_routing_confidence",
                "ai_business_context",
                "ai_routing_scope",
                "ai_affected_service",
                "ai_failure_domain",
                "ai_routing_reason",
                "ai_routing_input_hash",
            }.issubset(ticket_columns))
            survey_columns = {
                column["name"] for column in inspector.get_columns("surveys")
            }
            self.assertIn("response_token_hash", survey_columns)
            self.assertIn("active_delivery_key", survey_columns)
            self.assertIn("response_expires_at", survey_columns)
            self.assertIn("delivery_status", survey_columns)
            self.assertIn("delivery_message_id", survey_columns)
            survey_indexes = {
                index["name"]: index for index in inspector.get_indexes("surveys")
            }
            self.assertTrue(survey_indexes["ix_surveys_response_token_hash"]["unique"])
            self.assertTrue(survey_indexes["ix_surveys_active_delivery_key"]["unique"])
            response_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("survey_responses")
            }
            self.assertIn("uix_survey_response_once", response_constraints)
            for table_name, constraint_name in (
                ("ticket_status_config", "uix_ticket_status_config_name_key"),
                ("ticket_priority_config", "uix_ticket_priority_config_name_key"),
            ):
                columns = {
                    column["name"] for column in inspector.get_columns(table_name)
                }
                constraints = {
                    constraint["name"]
                    for constraint in inspector.get_unique_constraints(table_name)
                }
                self.assertIn("name_key", columns)
                self.assertIn(constraint_name, constraints)
            approval_columns = {
                column["name"]: column
                for column in inspector.get_columns("change_approvals")
            }
            self.assertTrue(approval_columns["approver_id"]["nullable"])
            user_columns = {
                column["name"] for column in inspector.get_columns("users")
            }
            user_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("users")
            }
            user_checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("users")
            }
            self.assertIn("email_key", user_columns)
            self.assertIn("uix_users_email_key", user_constraints)
            self.assertIn("ck_users_email_identity_canonical", user_checks)
            self.assertNotIn("user_mappings", inspector.get_table_names())
            session_columns = {
                column["name"]
                for column in inspector.get_columns("integration_sessions")
            }
            self.assertNotIn("user_id", session_columns)
            command.check(self.config)
        finally:
            engine.dispose()

    def test_routing_migration_accepts_bootstrap_compatible_columns(self):
        command.upgrade(self.config, "0031")
        engine = create_engine(self.url)
        routing_columns = {
            "ai_secondary_team": "VARCHAR",
            "ai_routing_confidence": "FLOAT",
            "ai_business_context": "VARCHAR",
            "ai_routing_scope": "VARCHAR",
            "ai_affected_service": "VARCHAR",
            "ai_failure_domain": "VARCHAR",
            "ai_routing_reason": "TEXT",
        }
        try:
            with engine.begin() as connection:
                for column_name, ddl in routing_columns.items():
                    connection.execute(text(
                        f"ALTER TABLE tickets ADD COLUMN {column_name} {ddl}"
                    ))
                connection.execute(text(
                    "INSERT INTO tickets "
                    "(id, subject, ai_suggested_team, ai_secondary_team, "
                    "ai_routing_confidence, ai_business_context, ai_routing_scope, "
                    "ai_affected_service, ai_failure_domain, ai_routing_reason) "
                    "VALUES ('routed-ticket', 'Preserve route', 'APP_WEB', "
                    "'APP_EDI_API', 0.91, 'UNKNOWN', 'service_wide', "
                    "'customer portal', 'web-layer failure', 'Observed portal error')"
                ))

            command.upgrade(self.config, "head")

            ticket_columns = {
                column["name"] for column in inspect(engine).get_columns("tickets")
            }
            self.assertTrue(set(routing_columns).issubset(ticket_columns))
            with engine.connect() as connection:
                route = connection.execute(text(
                    "SELECT ai_suggested_team, ai_secondary_team, "
                    "ai_routing_confidence, ai_business_context, ai_routing_scope, "
                    "ai_affected_service, ai_failure_domain, ai_routing_reason "
                    "FROM tickets WHERE id = 'routed-ticket'"
                )).mappings().one()
            self.assertEqual(route["ai_suggested_team"], "APP_WEB")
            self.assertEqual(route["ai_secondary_team"], "APP_EDI_API")
            self.assertAlmostEqual(route["ai_routing_confidence"], 0.91)
            self.assertEqual(route["ai_business_context"], "UNKNOWN")
            self.assertEqual(route["ai_routing_scope"], "service_wide")
            self.assertEqual(route["ai_affected_service"], "customer portal")
            self.assertEqual(route["ai_failure_domain"], "web-layer failure")
            self.assertEqual(route["ai_routing_reason"], "Observed portal error")
            self.assertEqual(self._current_revision(engine), "0033")
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
                connection.execute(text(
                    "INSERT INTO survey_templates (id, name, question, is_active) "
                    "VALUES (91, 'Legacy CSAT', 'How was it?', 1)"
                ))
                connection.execute(text(
                    "INSERT INTO surveys (id, ticket_id, template_id, sent_at) "
                    "VALUES ('legacy-survey', 'legacy-ticket', 91, CURRENT_TIMESTAMP)"
                ))
                connection.execute(text(
                    "INSERT INTO survey_responses (survey_id, rating, comment) VALUES "
                    "('legacy-survey', 4, 'first'), "
                    "('legacy-survey', 1, 'duplicate')"
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
                survey = connection.execute(text(
                    "SELECT delivery_status, response_token_hash "
                    "FROM surveys WHERE id = 'legacy-survey'"
                )).mappings().one()
                response_count = connection.execute(text(
                    "SELECT COUNT(*) FROM survey_responses "
                    "WHERE survey_id = 'legacy-survey'"
                )).scalar_one()
            self.assertEqual(ticket["subject"], "Preserve me")
            self.assertEqual(ticket["ticket_type"], "incident")
            self.assertEqual(ticket["workflow_status"], "New")
            self.assertEqual(user["name"], "Legacy User")
            self.assertEqual(user["role"], "agent")
            self.assertTrue(user["is_active"])
            self.assertEqual(survey["delivery_status"], "legacy")
            self.assertIsNone(survey["response_token_hash"])
            self.assertEqual(response_count, 1)
            self.assertEqual(self._current_revision(engine), "0033")
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
            self.assertEqual(self._current_revision(engine), "0033")
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

    def test_config_name_key_migration_fails_closed_on_ambiguous_legacy_names(self):
        command.upgrade(self.config, "0022")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO ticket_priority_config "
                    "(name, label, color, weight, sort_order) VALUES "
                    "('P1', 'Critical', 'red', 1, 0), "
                    "('p1', 'Conflicting critical', 'red', 999, 1)"
                ))

            with self.assertRaisesRegex(
                RuntimeError,
                "case-insensitive duplicate names",
            ):
                command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0022")
            inspector = inspect(engine)
            self.assertNotIn(
                "name_key",
                {column["name"] for column in inspector.get_columns("ticket_status_config")},
            )
            self.assertNotIn(
                "name_key",
                {column["name"] for column in inspector.get_columns("ticket_priority_config")},
            )

            with engine.begin() as connection:
                connection.execute(text(
                    "DELETE FROM ticket_priority_config WHERE name = 'p1'"
                ))
            command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_config_name_key_migration_rejects_nonportable_edge_whitespace(self):
        command.upgrade(self.config, "0022")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO ticket_priority_config "
                        "(name, label, color, weight, sort_order) VALUES "
                        "(:tab_name, 'Tab suffix', 'red', 1, 0), "
                        "(:nbsp_name, 'NBSP suffix', 'amber', 5, 1)"
                    ),
                    {"tab_name": "Custom\t", "nbsp_name": "Other\u00a0"},
                )

            with self.assertRaisesRegex(RuntimeError, "surrounding whitespace"):
                command.upgrade(self.config, "head")
            inspector = inspect(engine)
            for table_name in ("ticket_status_config", "ticket_priority_config"):
                self.assertNotIn(
                    "name_key",
                    {column["name"] for column in inspector.get_columns(table_name)},
                )
        finally:
            engine.dispose()

    def test_config_name_key_migration_rejects_priority_names_tickets_cannot_store(self):
        command.upgrade(self.config, "0022")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO ticket_priority_config "
                        "(name, label, color, weight, sort_order) VALUES "
                        "(:name, 'Overlong', 'red', 1, 0)"
                    ),
                    {"name": "x" * 33},
                )

            with self.assertRaisesRegex(RuntimeError, "overlong name"):
                command.upgrade(self.config, "head")
            inspector = inspect(engine)
            for table_name in ("ticket_status_config", "ticket_priority_config"):
                self.assertNotIn(
                    "name_key",
                    {column["name"] for column in inspector.get_columns(table_name)},
                )
        finally:
            engine.dispose()

    def test_user_email_key_migration_canonicalizes_and_rejects_duplicates(self):
        command.upgrade(self.config, "0024")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO users (id, name, email, role, is_active) VALUES "
                    "('first', 'First', ' Owner@Example.COM ', 'admin', 1), "
                    "('second', 'Second', 'owner@example.com', 'agent', 1)"
                ))

            with self.assertRaisesRegex(RuntimeError, "duplicate canonical emails"):
                command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0024")
            self.assertNotIn(
                "email_key",
                {column["name"] for column in inspect(engine).get_columns("users")},
            )

            with engine.begin() as connection:
                connection.execute(text(
                    "UPDATE users SET email = 'other@example.com' WHERE id = 'second'"
                ))
            command.upgrade(self.config, "head")

            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT id, email, email_key FROM users ORDER BY id"
                )).mappings().all()
                with self.assertRaises(IntegrityError):
                    connection.execute(text(
                        "INSERT INTO users (id, name, email, email_key) VALUES "
                        "('duplicate', 'Duplicate', 'owner@example.com', 'owner@example.com')"
                    ))
            with engine.begin() as connection:
                with self.assertRaises(IntegrityError):
                    connection.execute(text(
                        "INSERT INTO users (id, name, email) VALUES "
                        "('legacy-write', 'Legacy Write', 'legacy@example.com')"
                    ))
            with engine.begin() as connection:
                with self.assertRaises(IntegrityError):
                    connection.execute(text(
                        "INSERT INTO users (id, name, email, email_key) VALUES "
                        "('drifted', 'Drifted', ' Mixed@Example.COM ', 'mixed@example.com')"
                    ))
            self.assertEqual(
                [dict(row) for row in rows],
                [
                    {"id": "first", "email": "owner@example.com", "email_key": "owner@example.com"},
                    {"id": "second", "email": "other@example.com", "email_key": "other@example.com"},
                ],
            )
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_problem_status_migration_normalizes_the_legacy_investigation_value(self):
        command.upgrade(self.config, "0025")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO problems (id, title, status) VALUES "
                    "('legacy-problem', 'Legacy investigation', 'Investigating'), "
                    "('canonical-problem', 'Canonical investigation', 'Under Investigation')"
                ))

            command.upgrade(self.config, "head")

            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT id, status FROM problems ORDER BY id"
                )).mappings().all()
            self.assertEqual(
                [dict(row) for row in rows],
                [
                    {"id": "canonical-problem", "status": "Under Investigation"},
                    {"id": "legacy-problem", "status": "Under Investigation"},
                ],
            )
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_asset_status_migration_normalizes_unambiguous_legacy_values(self):
        command.upgrade(self.config, "0026")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO assets (id, name, asset_type, status) VALUES "
                    "('active', 'Active asset', 'Hardware', 'Active'), "
                    "('repair', 'Repair asset', 'Hardware', 'In Repair'), "
                    "('lost-stolen', 'Lost asset', 'Hardware', 'Lost/Stolen'), "
                    "('canonical', 'Canonical asset', 'Hardware', 'Retired')"
                ))

            command.upgrade(self.config, "head")

            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT id, status FROM assets ORDER BY id"
                )).mappings().all()
            self.assertEqual(
                [dict(row) for row in rows],
                [
                    {"id": "active", "status": "In Use"},
                    {"id": "canonical", "status": "Retired"},
                    {"id": "lost-stolen", "status": "Lost"},
                    {"id": "repair", "status": "Broken"},
                ],
            )
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_asset_status_migration_refuses_to_guess_inactive_semantics(self):
        command.upgrade(self.config, "0026")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO assets (id, name, asset_type, status) "
                    "VALUES ('inactive', 'Inactive asset', 'Hardware', 'Inactive')"
                ))

            with self.assertRaisesRegex(
                RuntimeError,
                "Cannot guess whether legacy asset status 'Inactive'",
            ):
                command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0026")
        finally:
            engine.dispose()

    def test_asset_status_migration_fails_closed_for_unknown_values(self):
        command.upgrade(self.config, "0026")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO assets (id, name, asset_type, status) "
                    "VALUES ('unknown', 'Unknown asset', 'Hardware', 'Quarantined')"
                ))

            with self.assertRaisesRegex(
                RuntimeError,
                "unknown lifecycle statuses: 'Quarantined'",
            ):
                command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0026")
        finally:
            engine.dispose()

    def test_change_completion_migration_enforces_canonical_lifecycle_rows(self):
        command.upgrade(self.config, "0027")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO changes (id, title, status, completed_at) VALUES "
                    "('draft', 'Draft change', 'Draft', NULL), "
                    "('submitted', 'Submitted change', 'Submitted', NULL), "
                    "('cab', 'CAB change', 'CAB Review', NULL), "
                    "('approved', 'Approved change', 'Approved', NULL), "
                    "('progress', 'Active change', 'In Progress', NULL), "
                    "('completed', 'Completed change', 'Completed', CURRENT_TIMESTAMP), "
                    "('rejected', 'Rejected change', 'Rejected', NULL), "
                    "('cancelled', 'Cancelled change', 'Cancelled', NULL)"
                ))

            command.upgrade(self.config, "head")

            inspector = inspect(engine)
            status_column = next(
                column
                for column in inspector.get_columns("changes")
                if column["name"] == "status"
            )
            check_names = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("changes")
            }
            self.assertFalse(status_column["nullable"])
            self.assertIn("ck_changes_status_completion", check_names)
            self.assertEqual(self._current_revision(engine), "0033")

            for values in (
                "('invalid-null', 'Null status', NULL, NULL)",
                "('invalid-completed', 'Missing completion', 'Completed', NULL)",
                "('invalid-draft', 'Unexpected completion', 'Draft', CURRENT_TIMESTAMP)",
                "('invalid-vocabulary', 'Unknown status', 'Rolled Back', NULL)",
            ):
                with self.assertRaises(IntegrityError):
                    with engine.begin() as connection:
                        connection.execute(text(
                            "INSERT INTO changes (id, title, status, completed_at) VALUES "
                            + values
                        ))
        finally:
            engine.dispose()

    def test_change_completion_migration_rejects_completed_without_timestamp(self):
        command.upgrade(self.config, "0027")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO changes (id, title, status, completed_at) "
                    "VALUES ('broken-completed', 'Broken history', 'Completed', NULL)"
                ))

            with self.assertRaisesRegex(RuntimeError, "broken-completed"):
                command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0027")
            self.assertTrue(next(
                column["nullable"]
                for column in inspect(engine).get_columns("changes")
                if column["name"] == "status"
            ))
        finally:
            engine.dispose()

    def test_change_completion_migration_rejects_noncompleted_timestamp(self):
        command.upgrade(self.config, "0027")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO changes (id, title, status, completed_at) "
                    "VALUES ('broken-draft', 'Broken history', 'Draft', CURRENT_TIMESTAMP)"
                ))

            with self.assertRaisesRegex(RuntimeError, "broken-draft"):
                command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0027")
        finally:
            engine.dispose()

    def test_change_completion_migration_rejects_null_or_unknown_status(self):
        command.upgrade(self.config, "0027")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO changes (id, title, status) VALUES "
                    "('null-status', 'Missing status', NULL), "
                    "('unknown-status', 'Unknown status', 'Rolled Back')"
                ))

            with self.assertRaisesRegex(RuntimeError, "null-status"):
                command.upgrade(self.config, "head")
            self.assertEqual(self._current_revision(engine), "0027")
        finally:
            engine.dispose()

    def test_escalation_risk_migration_marks_only_completed_legacy_values(self):
        command.upgrade(self.config, "0028")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO tickets "
                    "(id, subject, ai_reasoning, escalation_risk, created_at) VALUES "
                    "('legacy-zero', 'Needs zero backfill', 'analysis', 0, CURRENT_TIMESTAMP), "
                    "('legacy-null', 'Needs null backfill', 'analysis', NULL, CURRENT_TIMESTAMP), "
                    "('known-risk', 'Already computed', 'analysis', 42, CURRENT_TIMESTAMP), "
                    "('not-analyzed', 'No analysis yet', NULL, 0, CURRENT_TIMESTAMP)"
                ))

            command.upgrade(self.config, "head")

            with engine.connect() as connection:
                rows = {
                    row["id"]: row["escalation_risk_backfilled_at"]
                    for row in connection.execute(text(
                        "SELECT id, escalation_risk_backfilled_at FROM tickets "
                        "ORDER BY id"
                    )).mappings()
                }
            self.assertIsNone(rows["legacy-zero"])
            self.assertIsNone(rows["legacy-null"])
            self.assertIsNotNone(rows["known-risk"])
            self.assertIsNone(rows["not-analyzed"])
            indexes = {
                index["name"] for index in inspect(engine).get_indexes("tickets")
            }
            self.assertIn("ix_tickets_escalation_risk_backfill_pending", indexes)
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_external_projection_migration_clears_stale_live_state(self):
        command.upgrade(self.config, "0029")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO tickets "
                    "(id, subject, external_source, external_id, external_status, "
                    "external_due_by, external_fr_due_by, due_by, resolution_due_at, "
                    "response_due_at, resolved_at) VALUES "
                    "('provider-open', 'Reopened provider ticket', 'freshservice', "
                    "'provider-1', 'Open', NULL, NULL, '2026-08-30 10:00:00', "
                    "'2026-08-30 10:00:00', '2026-08-29 10:00:00', "
                    "'2026-08-26 10:00:00'), "
                    "('provider-current', 'Current provider deadlines', 'freshservice', "
                    "'provider-2', 'Pending', '2026-09-01 10:00:00', "
                    "'2026-08-31 10:00:00', '2026-08-30 10:00:00', "
                    "'2026-08-30 10:00:00', '2026-08-30 09:00:00', NULL), "
                    "('manual-local', 'Local ticket', 'manual', NULL, 'Open', NULL, NULL, "
                    "'2026-09-02 10:00:00', '2026-09-02 10:00:00', "
                    "'2026-09-02 09:00:00', '2026-08-25 10:00:00')"
                ))

            command.upgrade(self.config, "head")

            with engine.connect() as connection:
                open_row = connection.execute(text(
                    "SELECT due_by, resolution_due_at, response_due_at, resolved_at "
                    "FROM tickets WHERE id = 'provider-open'"
                )).mappings().one()
                aligned = connection.execute(text(
                    "SELECT COUNT(*) FROM tickets WHERE id = 'provider-current' "
                    "AND due_by = external_due_by "
                    "AND resolution_due_at = external_due_by "
                    "AND response_due_at = external_fr_due_by"
                )).scalar_one()
                manual = connection.execute(text(
                    "SELECT due_by, resolved_at FROM tickets WHERE id = 'manual-local'"
                )).mappings().one()
            self.assertTrue(all(value is None for value in open_row.values()))
            self.assertEqual(aligned, 1)
            self.assertIsNotNone(manual["due_by"])
            self.assertIsNotNone(manual["resolved_at"])
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_demo_bootstrap_forward_columns_upgrade_cleanly_from_0021(self):
        command.upgrade(self.config, "0021")
        engine = create_engine(self.url)
        try:
            with patch.object(database, "engine", engine):
                # Simulate the legacy demo bootstrap that existed before the
                # new fail-closed version guard. These migrations must still
                # adopt its already-compatible forward columns.
                Base.metadata.create_all(bind=engine)
                database._ensure_columns()

            # The authoritative migration must still adopt the already-compatible
            # survey schema left by the historical demo bootstrap.
            command.upgrade(self.config, "head")
            command.check(self.config)

            inspector = inspect(engine)
            survey_columns = {
                column["name"] for column in inspector.get_columns("surveys")
            }
            survey_indexes = {
                index["name"] for index in inspector.get_indexes("surveys")
            }
            survey_foreign_keys = {
                foreign_key["name"]
                for foreign_key in inspector.get_foreign_keys("surveys")
            }
            response_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "survey_responses"
                )
            }
            self.assertIn("response_token_hash", survey_columns)
            self.assertIn("ix_surveys_response_token_hash", survey_indexes)
            self.assertIn("fk_surveys_sent_by_users", survey_foreign_keys)
            self.assertIn("uix_survey_response_once", response_constraints)
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_demo_bootstrap_relaxes_legacy_approval_owner_and_purge_preserves_audit(self):
        command.upgrade(self.config, "0023")
        engine = create_engine(self.url)
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO users (id, name, role, is_active) VALUES "
                    "('admin', 'Admin', 'admin', 1), "
                    "('legacy-approver', 'Legacy Approver', 'agent', 0)"
                ))
                connection.execute(text(
                    "INSERT INTO changes (id, title, status, assigned_to) VALUES "
                    "('legacy-change', 'Preserve approval', 'Approved', 'legacy-approver')"
                ))
                connection.execute(text(
                    "INSERT INTO change_approvals "
                    "(change_id, approver_id, decision, comment, decided_at) VALUES "
                    "('legacy-change', 'legacy-approver', 'approved', "
                    "'Historical decision', CURRENT_TIMESTAMP)"
                ))

            with patch.object(database, "engine", engine):
                # Reproduce the former compatibility bootstrap directly; the
                # current init_db requires versioned demos to migrate first.
                Base.metadata.create_all(bind=engine)
                database._ensure_columns()

            # Historical demo compatibility code could run before an operator
            # later upgraded the same database. Migration 0025 deliberately
            # adopts that already-compatible schema.
            command.upgrade(self.config, "head")
            command.check(self.config)

            approval_columns = {
                column["name"]: column
                for column in inspect(engine).get_columns("change_approvals")
            }
            self.assertTrue(approval_columns["approver_id"]["nullable"])

            session_factory = database.sessionmaker(bind=engine)
            with session_factory() as db:
                admin = db.get(database.UserRecord, "admin")
                result = asyncio.run(
                    main.purge_user("legacy-approver", db=db, _user=admin)
                )
                self.assertEqual(result["anonymized_decided_approvals"], 1)

            with engine.connect() as connection:
                user_count = connection.execute(text(
                    "SELECT COUNT(*) FROM users WHERE id = 'legacy-approver'"
                )).scalar_one()
                change = connection.execute(text(
                    "SELECT status, assigned_to FROM changes "
                    "WHERE id = 'legacy-change'"
                )).mappings().one()
                approval = connection.execute(text(
                    "SELECT approver_id, decision, comment FROM change_approvals "
                    "WHERE change_id = 'legacy-change'"
                )).mappings().one()
            self.assertEqual(user_count, 0)
            self.assertEqual(change["status"], "Approved")
            self.assertIsNone(change["assigned_to"])
            self.assertIsNone(approval["approver_id"])
            self.assertEqual(approval["decision"], "approved")
            self.assertEqual(approval["comment"], "Historical decision")
            self.assertEqual(self._current_revision(engine), "0033")
        finally:
            engine.dispose()

    def test_production_startup_verifies_only_and_never_bootstraps(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "production"}),
            patch.object(database, "verify_database_schema") as verify,
            patch.object(database, "_verify_demo_schema_before_bootstrap") as demo_guard,
            patch.object(database.Base.metadata, "create_all") as create_all,
            patch.object(database, "_ensure_columns") as ensure_columns,
            patch.object(database, "_ensure_ticket_search_documents") as ensure_vectors,
        ):
            database.init_db()

        verify.assert_called_once_with()
        demo_guard.assert_not_called()
        create_all.assert_not_called()
        ensure_columns.assert_not_called()
        ensure_vectors.assert_not_called()

    def test_blank_app_mode_uses_production_verification_path(self):
        with (
            patch.dict(os.environ, {"APP_MODE": ""}),
            patch.object(database, "verify_database_schema") as verify,
            patch.object(database, "_verify_demo_schema_before_bootstrap") as demo_guard,
            patch.object(database.Base.metadata, "create_all") as create_all,
            patch.object(database, "_ensure_columns") as ensure_columns,
            patch.object(database, "_ensure_ticket_search_documents") as ensure_vectors,
        ):
            database.init_db()

        verify.assert_called_once_with()
        demo_guard.assert_not_called()
        create_all.assert_not_called()
        ensure_columns.assert_not_called()
        ensure_vectors.assert_not_called()

    def test_demo_startup_can_bootstrap_without_alembic(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "demo"}),
            patch.object(database, "verify_database_schema") as verify,
            patch.object(database, "_verify_demo_schema_before_bootstrap") as demo_guard,
            patch.object(database.Base.metadata, "create_all") as create_all,
            patch.object(database, "_ensure_columns") as ensure_columns,
            patch.object(database, "_ensure_ticket_search_documents") as ensure_vectors,
        ):
            database.init_db()

        verify.assert_not_called()
        demo_guard.assert_called_once_with()
        create_all.assert_called_once_with(bind=database.engine)
        ensure_columns.assert_called_once_with()
        ensure_vectors.assert_called_once_with()

    def test_demo_startup_rejects_behind_head_version_before_any_ddl(self):
        command.upgrade(self.config, "0002")
        engine = create_engine(self.url)
        try:
            tables_before = set(inspect(engine).get_table_names())
            ticket_columns_before = {
                column["name"] for column in inspect(engine).get_columns("tickets")
            }
            with (
                patch.dict(os.environ, {"APP_MODE": "demo"}),
                patch.object(database, "engine", engine),
                patch.object(database.Base.metadata, "create_all") as create_all,
                patch.object(database, "_ensure_columns") as ensure_columns,
                patch.object(database, "_ensure_ticket_search_documents") as ensure_vectors,
            ):
                with self.assertRaisesRegex(RuntimeError, "alembic upgrade head"):
                    database.init_db()

            create_all.assert_not_called()
            ensure_columns.assert_not_called()
            ensure_vectors.assert_not_called()
            self.assertEqual(self._current_revision(engine), "0002")
            self.assertEqual(set(inspect(engine).get_table_names()), tables_before)
            self.assertEqual(
                {
                    column["name"]
                    for column in inspect(engine).get_columns("tickets")
                },
                ticket_columns_before,
            )
        finally:
            engine.dispose()

    def test_demo_schema_guard_rejects_invalid_revision_sets(self):
        for current_heads in (set(), {"unknown"}, {"0033", "unexpected"}):
            with self.subTest(current_heads=current_heads):
                with (
                    patch.object(database, "_sa_inspect") as inspect_schema,
                    patch.object(
                        database,
                        "_database_revision_sets",
                        return_value=({"0033"}, current_heads),
                    ),
                ):
                    inspect_schema.return_value.has_table.return_value = True
                    with self.assertRaisesRegex(RuntimeError, "migration recovery"):
                        database._verify_demo_schema_before_bootstrap()

    def test_demo_schema_guard_accepts_matching_multiple_heads(self):
        with (
            patch.object(database, "_sa_inspect") as inspect_schema,
            patch.object(
                database,
                "_database_revision_sets",
                return_value=({"head-a", "head-b"}, {"head-a", "head-b"}),
            ),
        ):
            inspect_schema.return_value.has_table.return_value = True
            database._verify_demo_schema_before_bootstrap()

    def test_head_demo_startup_passes_guard_and_bootstraps(self):
        command.upgrade(self.config, "head")
        engine = create_engine(self.url)
        try:
            with (
                patch.dict(os.environ, {"APP_MODE": "demo"}),
                patch.object(database, "engine", engine),
                patch.object(database.Base.metadata, "create_all") as create_all,
                patch.object(database, "_ensure_columns") as ensure_columns,
                patch.object(database, "_ensure_ticket_search_documents") as ensure_vectors,
            ):
                database.init_db()

            create_all.assert_called_once_with(bind=engine)
            ensure_columns.assert_called_once_with()
            ensure_vectors.assert_called_once_with()
        finally:
            engine.dispose()

    def test_unversioned_demo_bootstrap_is_repeatable(self):
        engine = create_engine(self.url)
        try:
            with (
                patch.dict(os.environ, {"APP_MODE": "demo"}),
                patch.object(database, "engine", engine),
                patch.object(database, "_ensure_ticket_search_documents"),
            ):
                database.init_db()
                database.init_db()

            tables = set(inspect(engine).get_table_names())
            self.assertNotIn("alembic_version", tables)
            self.assertEqual(tables, set(Base.metadata.tables))
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
