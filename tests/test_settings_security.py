import asyncio
import os
import socket
import unittest
from unittest.mock import patch

from app.backend import main, settings, ticket_vectors


class SettingsSecurityTests(unittest.TestCase):
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

    def test_invalid_default_model_is_rejected_before_it_is_persisted(self):
        with (
            patch.object(settings, "_write_db_overrides") as write_overrides,
            self.assertRaises(ValueError),
        ):
            settings.update_settings({"DEFAULT_MODEL": "unqualified-model"})
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

    def test_production_startup_never_runs_demo_seed_with_stale_flag(self):
        old_manager = main.llm_mgr
        old_engine_manager = main.engine.llm
        try:
            with (
                patch.dict(os.environ, {"APP_MODE": "production", "SEED_DEMO_DATA": "true"}, clear=False),
                patch.object(main, "init_db"),
                patch.object(main.settings_module, "load_settings_into_env"),
                patch.object(main.settings_module, "is_demo_mode", return_value=False),
                patch.object(main, "LLMManager"),
                patch.object(main, "start_sync_worker"),
                patch("app.backend.seed.run_seed") as run_seed,
            ):
                asyncio.run(main.startup())
        finally:
            main.llm_mgr = old_manager
            main.engine.llm = old_engine_manager

        run_seed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
