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
            "CUSTOM_PROVIDER_TYPE": "openai",
            "CUSTOM_API_VERSION": "2024-10-21",
            "CUSTOM_TEMPERATURE": "0.7",
            "CUSTOM_MAX_TOKENS": "512",
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

    def test_same_model_changes_identity_when_effective_config_changes(self):
        baseline = self._custom_identity()
        changes = {
            "provider_type": {"CUSTOM_PROVIDER_TYPE": "anthropic"},
            "api_version": {"CUSTOM_API_VERSION": "2025-01-01"},
            "temperature": {"CUSTOM_TEMPERATURE": "0.8"},
            "token_cap": {"CUSTOM_MAX_TOKENS": "1024"},
        }

        for label, override in changes.items():
            with self.subTest(label=label):
                self.assertNotEqual(
                    baseline,
                    self._custom_identity(**override),
                )

    def test_credential_rotation_does_not_create_a_persisted_secret_verifier(self):
        baseline = self._custom_identity()
        rotated = self._custom_identity(CUSTOM_API_KEY="sk-different-secret")

        self.assertEqual(baseline, rotated)

    def test_openai_default_and_explicit_default_endpoint_are_equivalent(self):
        environment = {
            "APP_MODE": "demo",
            "OPENAI_API_KEY": "sk-openai-secret",
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "true",
        }
        with patch.dict(os.environ, environment, clear=True):
            implicit = LLMManager("openai/gpt-4.1-mini")
        environment["OPENAI_API_BASE"] = "https://api.openai.com/v1/"
        with patch.dict(os.environ, environment, clear=True):
            explicit = LLMManager("openai/gpt-4.1-mini")

        self.assertEqual(implicit.cache_identity, explicit.cache_identity)

    def test_identity_rejects_an_unvalidated_provider_endpoint(self):
        with patch.dict(os.environ, {
            "APP_MODE": "demo",
            "OPENAI_API_KEY": "sk-openai-secret",
            "OPENAI_API_BASE": "https://provider.example/v1?tenant=secret",
            "LLM_ALLOW_PRIVATE_ENDPOINTS": "true",
        }, clear=True):
            manager = LLMManager("openai/gpt-4.1-mini")
            with self.assertRaisesRegex(ValueError, "query string"):
                _ = manager.cache_identity


if __name__ == "__main__":
    unittest.main()
