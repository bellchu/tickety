import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.backend import llm_manager, main


class ModelCatalogRefreshDiagnosticsTests(unittest.TestCase):
    def test_background_refresh_preserves_existing_failure_tolerance(self):
        with (
            patch.dict(
                os.environ,
                {
                    "FOUNDRY_API_BASE": "https://resource.services.ai.azure.com/openai/v1",
                    "FOUNDRY_API_KEY": "catalog-secret",
                    "FOUNDRY_AUTH_METHOD": "api_key",
                },
                clear=True,
            ),
            patch.object(
                llm_manager,
                "_fetch_openai_compatible_models",
                new=AsyncMock(
                    side_effect=ValueError(
                        "LLM base URL hostname could not be resolved"
                    )
                ),
            ),
            patch.object(llm_manager, "_save_fetched_models"),
        ):
            result = asyncio.run(llm_manager.fetch_live_models())

        self.assertEqual(result, {})

    def test_manual_refresh_reports_safe_dns_failure(self):
        secret = "catalog-secret-must-not-leak"
        with (
            patch.dict(
                os.environ,
                {
                    "FOUNDRY_API_BASE": "https://resource.services.ai.azure.com/openai/v1",
                    "FOUNDRY_API_KEY": secret,
                    "FOUNDRY_AUTH_METHOD": "api_key",
                },
                clear=True,
            ),
            patch.object(
                llm_manager,
                "_fetch_openai_compatible_models",
                new=AsyncMock(
                    side_effect=ValueError(
                        "LLM base URL hostname could not be resolved"
                    )
                ),
            ),
            patch.object(llm_manager, "_save_fetched_models"),
        ):
            with self.assertRaises(llm_manager.ModelCatalogRefreshError) as raised:
                asyncio.run(
                    llm_manager.fetch_live_models(raise_on_failure=True)
                )

        self.assertEqual(
            raised.exception.failures,
            {"foundry": "dns_resolution_failed"},
        )
        self.assertIn("DNS could not resolve", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))

    def test_manual_refresh_reports_partial_provider_failure(self):
        async def fetch(_key, _base, *, provider):
            if provider == "foundry":
                return [{"id": "foundry/model-a", "label": "model-a"}]
            raise llm_manager.httpx.TimeoutException("provider timeout")

        with (
            patch.dict(
                os.environ,
                {
                    "FOUNDRY_API_BASE": "https://resource.services.ai.azure.com/openai/v1",
                    "FOUNDRY_API_KEY": "foundry-secret",
                    "FOUNDRY_AUTH_METHOD": "api_key",
                    "CUSTOM_API_BASE": "https://provider.example/v1",
                    "CUSTOM_API_KEY": "custom-secret",
                },
                clear=True,
            ),
            patch.object(
                llm_manager,
                "_fetch_openai_compatible_models",
                new=AsyncMock(side_effect=fetch),
            ),
            patch.object(llm_manager, "_save_fetched_models") as save,
        ):
            with self.assertRaises(llm_manager.ModelCatalogRefreshError) as raised:
                asyncio.run(
                    llm_manager.fetch_live_models(raise_on_failure=True)
                )

        self.assertEqual(
            raised.exception.failures,
            {"custom": "request_timeout"},
        )
        save.assert_called_once_with(
            {"foundry": [{"id": "foundry/model-a", "label": "model-a"}]}
        )

    def test_refresh_route_converts_diagnostic_to_safe_bad_gateway(self):
        failure = llm_manager.ModelCatalogRefreshError(
            {"foundry": "dns_resolution_failed"}
        )
        with (
            patch.object(main, "_reserve_ai_request"),
            patch.object(
                llm_manager,
                "fetch_live_models",
                new=AsyncMock(side_effect=failure),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    main.refresh_models(
                        db=MagicMock(),
                        user=SimpleNamespace(id="admin-1"),
                    )
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail, str(failure))


if __name__ == "__main__":
    unittest.main()
