import asyncio
import os
import socket
import unittest
from unittest.mock import MagicMock, patch

from app.backend import main, settings, ticket_vectors, worker


class SettingsSecurityTests(unittest.TestCase):
    def setUp(self):
        # The developer's local .env may intentionally be production-like;
        # individual tests opt into production explicitly when required.
        self.environment = patch.dict(os.environ, {
            "APP_MODE": "demo",
            "LLM_ALLOWED_PROVIDER_HOSTS": "",
        }, clear=False)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_invalid_nonempty_app_mode_fails_closed(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "prodution"}, clear=False),
            self.assertRaisesRegex(ValueError, "APP_MODE"),
        ):
            settings.app_mode()

    def test_sensitive_settings_never_disclose_a_secret_prefix(self):
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-live-secret",
            "DATABASE_URL": "postgresql://tickety:database-password@db/tickety",
        }, clear=False):
            result = settings.get_settings()

        self.assertEqual(result["OPENAI_API_KEY"], "****")
        self.assertTrue(result["OPENAI_API_KEY__set"])
        self.assertNotIn("sk-live", result["OPENAI_API_KEY"])
        self.assertEqual(result["DATABASE_URL"], "****")
        self.assertTrue(result["DATABASE_URL__set"])
        self.assertNotIn("database-password", result["DATABASE_URL"])

    def test_demo_mode_cannot_enable_automatic_ai_from_stale_settings(self):
        with patch.dict(os.environ, {
            "APP_MODE": "demo",
            "AUTO_TRIAGE_ENABLED": "true",
        }, clear=False):
            self.assertFalse(settings.automation_enabled("AUTO_TRIAGE_ENABLED"))

    def test_llm_base_urls_reject_credentials_and_private_targets(self):
        with patch.dict(os.environ, {
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "false",
            "LLM_ALLOW_INSECURE_ENDPOINTS": "false",
        }, clear=False):
            with self.assertRaisesRegex(ValueError, "credentials"):
                settings._validate_llm_base_url("https://key@example.com/v1")
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                settings._validate_llm_base_url("http://example.com/v1")
            with patch.object(socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 443))]):
                with self.assertRaisesRegex(ValueError, "private or reserved"):
                    settings._validate_llm_base_url("https://provider.example/v1")

    def test_llm_base_url_accepts_resolved_public_https_target(self):
        with (
            patch.dict(os.environ, {"LLM_ALLOW_PRIVATE_ENDPOINTS": "false"}, clear=False),
            patch.object(socket, "getaddrinfo", return_value=[(None, None, None, None, ("203.0.113.10", 443))]),
        ):
            # TEST-NET is reserved, so use a known globally-routable fixture IP.
            with patch.object(socket, "getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 443))]):
                self.assertEqual(
                    settings._validate_llm_base_url("https://provider.example/v1/"),
                    "https://provider.example/v1",
                )

    def test_production_custom_provider_requires_exact_hostname_allowlist(self):
        with patch.dict(os.environ, {
            "APP_MODE": "production",
            "LLM_ALLOWED_PROVIDER_HOSTS": "",
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "false",
        }, clear=False):
            with self.assertRaisesRegex(ValueError, "LLM_ALLOWED_PROVIDER_HOSTS"):
                settings._validate_llm_base_url("https://provider.example/v1")

        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "LLM_ALLOWED_PROVIDER_HOSTS": "provider.example",
                "LLM_ALLOW_PRIVATE_ENDPOINTS": "false",
            }, clear=False),
            patch.object(socket, "getaddrinfo", return_value=[
                (None, None, None, None, ("8.8.8.8", 443))
            ]),
        ):
            self.assertEqual(
                settings._validate_llm_base_url("https://provider.example/v1"),
                "https://provider.example/v1",
            )

    def test_invalid_default_model_is_rejected_before_it_is_persisted(self):
        with (
            patch.object(settings, "_write_db_overrides") as write_overrides,
            self.assertRaises(ValueError),
        ):
            settings.update_settings({"DEFAULT_MODEL": "unqualified-model"})
        write_overrides.assert_not_called()

    def test_changing_provider_origin_requires_credential_reentry(self):
        with (
            patch.dict(os.environ, {
                "OPENAI_API_BASE": "https://api.openai.com/v1",
                "OPENAI_API_KEY": "existing-secret",
            }, clear=False),
            patch.object(settings, "_write_db_overrides") as write_overrides,
            patch.object(settings, "_reset_runtime"),
            self.assertRaisesRegex(ValueError, "requires re-entering OPENAI_API_KEY"),
        ):
            settings.update_settings({
                "OPENAI_API_BASE": "https://provider.example/v1",
            })
        write_overrides.assert_not_called()

    def test_custom_sampling_controls_reject_unbounded_values(self):
        for payload in (
            {"CUSTOM_MAX_TOKENS": "4097"},
            {"CUSTOM_MAX_TOKENS": "not-an-int"},
            {"CUSTOM_TEMPERATURE": "nan"},
            {"CUSTOM_TEMPERATURE": "2.1"},
        ):
            with self.subTest(payload=payload), patch.object(
                settings, "_write_db_overrides"
            ) as write_overrides, self.assertRaises(ValueError):
                settings.update_settings(payload)
            write_overrides.assert_not_called()

    def test_invalid_settings_batch_does_not_partially_mutate_process_environment(self):
        with patch.dict(os.environ, {"CUSTOM_API_KEY": "existing-key"}, clear=False):
            with patch.object(settings, "_write_db_overrides") as write_overrides:
                with self.assertRaises(ValueError):
                    settings.update_settings({
                        "CUSTOM_API_KEY": "replacement-key",
                        "CUSTOM_TEMPERATURE": "nan",
                    })
                self.assertEqual(os.environ["CUSTOM_API_KEY"], "existing-key")
                write_overrides.assert_not_called()

    def test_startup_revalidates_legacy_llm_base_url_overrides(self):
        with (
            patch.object(settings, "_read_db_overrides", return_value={
                "CUSTOM_API_BASE": "http://169.254.169.254/latest"
            }),
            patch.dict(os.environ, {
                "LLM_ALLOW_PRIVATE_ENDPOINTS": "false",
                "LLM_ALLOW_INSECURE_ENDPOINTS": "false",
            }, clear=False),
        ):
            with self.assertRaises(ValueError):
                settings.load_settings_into_env()

    def test_startup_revalidates_process_environment_embedding_url(self):
        with (
            patch.object(settings, "_read_db_overrides", return_value={}),
            patch.dict(os.environ, {
                "TICKET_EMBEDDING_API_BASE": "http://127.0.0.1/v1",
                "LLM_ALLOW_PRIVATE_ENDPOINTS": "false",
                "LLM_ALLOW_INSECURE_ENDPOINTS": "false",
            }, clear=False),
        ):
            with self.assertRaises(ValueError):
                settings.load_settings_into_env()

    def test_embedding_dispatch_revalidates_effective_destination(self):
        with (
            patch.dict(os.environ, {
                "TICKET_EMBEDDING_MODEL": "custom/embed",
                "CUSTOM_API_KEY": "configured",
                "CUSTOM_API_BASE": "https://provider.example/v1",
                "LLM_ALLOW_PRIVATE_ENDPOINTS": "false",
            }, clear=False),
            patch.object(socket, "getaddrinfo", return_value=[
                (None, None, None, None, ("127.0.0.1", 443))
            ]),
        ):
            with self.assertRaisesRegex(ValueError, "private or reserved"):
                ticket_vectors._embedding_kwargs()

    def test_runtime_mode_and_demo_seed_flags_are_not_database_mutable(self):
        with (
            patch.dict(os.environ, {"APP_MODE": "production", "SEED_DEMO_DATA": "false"}, clear=False),
            patch.object(settings, "_write_db_overrides") as write_overrides,
            patch.object(settings, "_reset_runtime"),
        ):
            settings.update_settings({
                "APP_MODE": "demo",
                "SEED_DEMO_DATA": "true",
                "ORG_NAME": "Example Support",
            })

            self.assertEqual(os.environ["APP_MODE"], "production")
            self.assertEqual(os.environ["SEED_DEMO_DATA"], "false")
            write_overrides.assert_called_once_with({"ORG_NAME": "Example Support"})

    def test_production_ignores_database_provider_and_security_overrides(self):
        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "OPENAI_API_KEY": "reviewed-deployment-key",
                "CORS_ALLOW_ORIGINS": "https://tickety.example",
                "OPENAI_API_BASE": "",
                "AUTO_TRIAGE_ENABLED": "false",
                "LLM_DAILY_TOKEN_BUDGET": "500000",
                "LLM_MAX_CONCURRENCY": "4",
                "ITSM_PROVIDER": "",
                "FRESHSERVICE_DOMAIN": "support.example.com",
                "JIRA_BASE_URL": "https://jira.example.com",
                "SYNC_INTERVAL_SECONDS": "60",
                "OPENROUTER_API_BASE": "",
                "AZURE_API_BASE": "",
                "AZURE_AI_API_BASE": "",
                "CUSTOM_API_BASE": "",
                "TICKET_EMBEDDING_API_BASE": "",
            }, clear=False),
            patch.object(settings, "_read_db_overrides", return_value={
                "OPENAI_API_KEY": "stale-database-key",
                "CORS_ALLOW_ORIGINS": "*",
                "AUTO_TRIAGE_ENABLED": "true",
                "LLM_DAILY_TOKEN_BUDGET": "100000000",
                "LLM_MAX_CONCURRENCY": "32",
                "ITSM_PROVIDER": "freshservice",
                "FRESHSERVICE_DOMAIN": "attacker.example",
                "JIRA_BASE_URL": "https://attacker.example",
                "SYNC_INTERVAL_SECONDS": "1",
            }),
        ):
            settings.load_settings_into_env()
            self.assertEqual(os.environ["OPENAI_API_KEY"], "reviewed-deployment-key")
            self.assertEqual(os.environ["CORS_ALLOW_ORIGINS"], "https://tickety.example")
            self.assertEqual(os.environ["AUTO_TRIAGE_ENABLED"], "false")
            self.assertEqual(os.environ["LLM_DAILY_TOKEN_BUDGET"], "500000")
            self.assertEqual(os.environ["LLM_MAX_CONCURRENCY"], "4")
            self.assertEqual(os.environ["ITSM_PROVIDER"], "")
            self.assertEqual(os.environ["FRESHSERVICE_DOMAIN"], "support.example.com")
            self.assertEqual(os.environ["JIRA_BASE_URL"], "https://jira.example.com")
            self.assertEqual(os.environ["SYNC_INTERVAL_SECONDS"], "60")

    def test_production_settings_update_cannot_change_deployment_owned_ai_keys(self):
        with (
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "OPENAI_API_KEY": "reviewed-deployment-key",
                "AUTO_TRIAGE_ENABLED": "false",
                "LLM_DAILY_TOKEN_BUDGET": "500000",
                "ITSM_PROVIDER": "",
                "FRESHSERVICE_DOMAIN": "support.example.com",
            }, clear=False),
            patch.object(settings, "_write_db_overrides") as write_overrides,
        ):
            settings.update_settings({
                "OPENAI_API_KEY": "runtime-attacker-key",
                "AUTO_TRIAGE_ENABLED": "true",
                "LLM_DAILY_TOKEN_BUDGET": "100000000",
                "ITSM_PROVIDER": "freshservice",
                "FRESHSERVICE_DOMAIN": "attacker.example",
            })
            self.assertEqual(os.environ["OPENAI_API_KEY"], "reviewed-deployment-key")
            self.assertEqual(os.environ["AUTO_TRIAGE_ENABLED"], "false")
            self.assertEqual(os.environ["LLM_DAILY_TOKEN_BUDGET"], "500000")
            self.assertEqual(os.environ["ITSM_PROVIDER"], "")
            self.assertEqual(os.environ["FRESHSERVICE_DOMAIN"], "support.example.com")
            write_overrides.assert_not_called()

    def test_unknown_database_rows_never_become_environment_variables(self):
        os.environ.pop("TICKET_INDEX_PRIVATE_COMMENTS", None)
        with (
            patch.object(settings, "_read_db_overrides", return_value={
                "TICKET_INDEX_PRIVATE_COMMENTS": "true",
            }),
            patch.dict(os.environ, {
                "APP_MODE": "production",
                "OPENAI_API_BASE": "",
                "OPENROUTER_API_BASE": "",
                "AZURE_API_BASE": "",
                "AZURE_AI_API_BASE": "",
                "CUSTOM_API_BASE": "",
                "TICKET_EMBEDDING_API_BASE": "",
            }, clear=False),
        ):
            settings.load_settings_into_env()
        self.assertNotIn("TICKET_INDEX_PRIVATE_COMMENTS", os.environ)

    def test_production_startup_never_runs_demo_seed_with_stale_flag(self):
        old_manager = main.llm_mgr
        old_engine_manager = main.engine.llm
        try:
            with (
                patch.dict(os.environ, {"APP_MODE": "production", "SEED_DEMO_DATA": "true"}, clear=False),
                patch.object(main, "init_db"),
                patch.object(main.settings_module, "load_settings_into_env"),
                patch.object(main.settings_module, "is_demo_mode", return_value=False),
                patch.object(main.settings_module, "is_production_mode", return_value=True),
                patch.object(main, "_disable_seeded_demo_identities", return_value=0),
                patch.object(main, "_prune_ai_operational_data", return_value={}),
                patch.object(main, "LLMManager"),
                patch.object(main, "start_sync_worker"),
                patch("app.backend.seed.run_seed") as run_seed,
            ):
                asyncio.run(main.startup())
        finally:
            main.llm_mgr = old_manager
            main.engine.llm = old_engine_manager

        run_seed.assert_not_called()

    def test_production_worker_runs_security_transition_before_scheduler(self):
        cleanup_db = MagicMock()
        order = []
        with (
            patch.object(worker, "init_db"),
            patch.object(worker.settings_module, "load_settings_into_env"),
            patch.object(worker.settings_module, "is_production_mode", return_value=True),
            patch.object(worker, "SessionLocal", return_value=cleanup_db),
            patch.object(
                worker,
                "disable_seeded_demo_identities",
                side_effect=lambda db: order.append(("transition", db)) or 0,
            ),
            patch.object(
                worker.ticket_vectors,
                "purge_private_comment_documents",
                side_effect=lambda db: order.append(("purge", db)) or 0,
            ),
            patch.object(worker, "process_role", return_value="worker"),
            patch.object(worker, "start_sync_worker", side_effect=lambda: order.append(("start", None)) or False),
        ):
            self.assertEqual(worker.run(), 1)

        self.assertEqual([item[0] for item in order], ["transition", "purge", "start"])
        cleanup_db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
