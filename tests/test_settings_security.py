import asyncio
import os
import unittest
from unittest.mock import patch

from app.backend import main, settings


class SettingsSecurityTests(unittest.TestCase):
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
