import io
import json
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.backend import llm_manager
from app.backend.llm_manager import LLMManager
from app.backend.privacy import redact_data, redact_text


class ExactSecretPrivacyTests(unittest.TestCase):
    def test_exact_secrets_are_redacted_without_a_label_at_every_depth(self):
        secret = "quartzFable9Zebra"
        self.assertIn(secret, redact_text(f"unlabeled: {secret}"))

        redacted = redact_data(
            {
                "summary": f"The provider repeated {secret} verbatim.",
                "nested": [secret, {secret: f"prefix-{secret}-suffix"}],
            },
            exact_secrets=(secret,),
        )

        serialized = json.dumps(redacted, sort_keys=True)
        self.assertNotIn(secret, serialized)
        self.assertIn("[secret]", serialized)


class LLMExactSecretBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_secret_is_removed_from_prompt_and_returned_output(self):
        secret = "quartzFable9Zebra"
        foreign_secret = "opaqueWebhookValue7Kite"
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "summary": f"The configured values were {secret} and {foreign_secret}.",
                "nested": [secret, foreign_secret],
            })))],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

        with patch.dict(
            os.environ,
            {
                "APP_MODE": "demo",
                "OPENAI_API_KEY": secret,
                "WEBHOOK_SECRET": foreign_secret,
                "LLM_PERSIST_METRICS": "false",
                "LLM_ENFORCE_PROVIDER_LIMITS": "false",
            },
            clear=True,
        ):
            manager = LLMManager("openai/gpt-4o")
            completion = AsyncMock(return_value=response)
            output = io.StringIO()
            with patch.object(llm_manager, "acompletion", completion):
                with redirect_stdout(output):
                    result = await manager.analyze(
                        f"Analyze these unlabeled values: {secret} {foreign_secret}"
                    )

        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(foreign_secret, serialized)
        self.assertIn("[secret]", serialized)
        self.assertNotIn(secret, output.getvalue())
        self.assertNotIn(foreign_secret, output.getvalue())
        sent_messages = completion.await_args.kwargs["messages"]
        self.assertNotIn(secret, json.dumps(sent_messages))
        self.assertNotIn(foreign_secret, json.dumps(sent_messages))

    async def test_fetched_provider_output_is_redacted_before_save_and_return(self):
        secret = "quartzFable9Zebra"
        provider_models = [{
            "id": "openai/gpt-safe-model",
            "label": f"Provider echoed {secret}",
        }]

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": secret},
            clear=True,
        ):
            with patch.object(
                llm_manager,
                "_fetch_openai_models",
                AsyncMock(return_value=provider_models),
            ), patch.object(llm_manager, "_save_fetched_models") as save_models:
                result = await llm_manager.fetch_live_models()

        returned = json.dumps(result, sort_keys=True)
        persisted = json.dumps(save_models.call_args.args[0], sort_keys=True)
        self.assertNotIn(secret, returned)
        self.assertNotIn(secret, persisted)
        self.assertIn("[secret]", returned)


if __name__ == "__main__":
    unittest.main()
