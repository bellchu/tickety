import os
import re
import unittest
from unittest.mock import patch

from app.backend.llm_manager import LLMManager


class LLMCacheIdentityTests(unittest.TestCase):
    def _custom_identity(self, **overrides: str) -> str:
        environment = {
            "APP_MODE": "demo",
            "CUSTOM_API_KEY": "sk-cache-identity-secret",
            "CUSTOM_API_BASE": "https://provider-a.example/v1",
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "true",
        }
        environment.update(overrides)
        with patch.dict(os.environ, environment, clear=True):
            return LLMManager("custom/shared-model").cache_identity

    def test_identity_is_stable_opaque_and_secret_safe(self):
        first = self._custom_identity()
        second = self._custom_identity(CUSTOM_API_BASE="https://provider-a.example/v1/")

        self.assertEqual(first, second)
        self.assertRegex(
            first,
            re.compile(r"^llm-provider-v1:[0-9a-f]{64}$"),
        )
        self.assertNotIn("provider-a.example", first)
        self.assertNotIn("sk-cache-identity-secret", first)
        self.assertNotIn("shared-model", first)

    def test_same_model_changes_identity_when_validated_endpoint_changes(self):
        first = self._custom_identity()
        second = self._custom_identity(
            CUSTOM_API_BASE="https://provider-b.example/v1"
        )

        self.assertNotEqual(first, second)

    def test_existing_manager_identity_tracks_current_dispatch_config(self):
        environment = {
            "APP_MODE": "demo",
            "CUSTOM_API_KEY": "sk-cache-identity-secret",
            "CUSTOM_API_BASE": "https://provider-a.example/v1",
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "true",
        }
        with patch.dict(os.environ, environment, clear=True):
            manager = LLMManager("custom/shared-model")
            first = manager.cache_identity
            os.environ["CUSTOM_API_BASE"] = "https://provider-b.example/v1"
            second = manager.cache_identity

        self.assertNotEqual(first, second)

    def test_removed_custom_tuning_knobs_do_not_affect_identity(self):
        baseline = self._custom_identity()
        self.assertEqual(
            baseline,
            self._custom_identity(
                CUSTOM_PROVIDER_TYPE="anthropic",
                CUSTOM_API_VERSION="2025-01-01",
                CUSTOM_TEMPERATURE="0.8",
                CUSTOM_MAX_TOKENS="1024",
            ),
        )

    def test_credential_rotation_does_not_create_a_persisted_secret_verifier(self):
        baseline = self._custom_identity()
        rotated = self._custom_identity(CUSTOM_API_KEY="sk-different-secret")

        self.assertEqual(baseline, rotated)

    def test_foundry_endpoint_trailing_slash_is_canonicalized(self):
        environment = {
            "APP_MODE": "demo",
            "FOUNDRY_API_KEY": "foundry-secret",
            "FOUNDRY_API_BASE": "https://resource.services.ai.azure.com/openai/v1",
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "true",
        }
        with patch.dict(os.environ, environment, clear=True):
            implicit = LLMManager("foundry/DeepSeek-V4-Flash")
        environment["FOUNDRY_API_BASE"] += "/"
        with patch.dict(os.environ, environment, clear=True):
            explicit = LLMManager("foundry/DeepSeek-V4-Flash")

        self.assertEqual(implicit.cache_identity, explicit.cache_identity)

    def test_identity_rejects_an_unvalidated_provider_endpoint(self):
        with patch.dict(os.environ, {
            "APP_MODE": "demo",
            "CUSTOM_API_KEY": "custom-secret",
            "CUSTOM_API_BASE": "https://provider.example/v1?tenant=secret",
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "true",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "query string"):
                LLMManager("custom/gpt-4.1-mini")


if __name__ == "__main__":
    unittest.main()
