import os
import asyncio
import json
import httpx
from litellm import acompletion
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────
# Provider catalog
#
# Tickety uses LiteLLM as a universal router. A "model" is just a LiteLLM
# model string; the *prefix* of that string selects the provider, which in
# turn decides which env vars (API key / base URL / api version) to use.
#
#   deepseek-v4-flash              -> DeepSeek (OpenAI-compatible surface)
#   openai/gpt-4o                  -> OpenAI
#   openrouter/anthropic/claude... -> OpenRouter (any vendor it aggregates)
#   azure/<deployment-name>        -> Azure OpenAI (AI Foundry)
#   azure_ai/<model>               -> Azure AI Foundry "models as a service"
#                                     (Llama, Mistral, etc. via Foundry)
#
# Adding a new provider = add an entry to PROVIDERS + register its env keys in
# settings.py / schema.py. No other code changes required.
# ──────────────────────────────────────────────────────────────────────────

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}
DEFAULT_MODEL = "deepseek-v4-flash"

# A provider entry:
#   label            : human label for the UI
#   match            : callable(model) -> bool used by resolve_provider()
#   env_keys         : list of {key,label,secret,placeholder} the UI renders
#   build            : callable(self, model) -> kwargs dict for litellm.acomplete
#   models           : list of {id,label} preset choices (empty = free text)
#   free_text_model  : when True, the UI shows a text input instead of a list
PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "models": [
            {"id": "deepseek-v4-flash", "label": "V4 Flash (fast, default)"},
            {"id": "deepseek-v4-pro", "label": "V4 Pro (reasoning)"},
        ],
        "free_text_model": False,
        "env_keys": [
            {"key": "DEEPSEEK_API_KEY", "label": "DeepSeek API Key", "secret": True, "placeholder": "sk-…"},
        ],
        "match": lambda m: m in DEEPSEEK_MODELS or m.startswith("deepseek-"),
        "build": lambda self, model: {
            "model": model,
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "custom_llm_provider": "openai",
            "api_base": DEEPSEEK_BASE_URL,
            # V4 defaults to thinking=enabled; disable for fast structured output.
            "extra_body": {"thinking": {"type": "disabled"}},
        },
    },
    "openai": {
        "label": "OpenAI",
        "models": [
            {"id": "openai/gpt-4o", "label": "GPT-4o"},
            {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini"},
            {"id": "openai/gpt-4.1", "label": "GPT-4.1"},
            {"id": "openai/gpt-4.1-mini", "label": "GPT-4.1 mini"},
        ],
        "free_text_model": False,
        "env_keys": [
            {"key": "OPENAI_API_KEY", "label": "OpenAI API Key", "secret": True, "placeholder": "sk-…"},
            {"key": "OPENAI_API_BASE", "label": "OpenAI-compatible Base URL (optional)", "secret": False, "placeholder": "https://api.openai.com/v1"},
        ],
        "match": lambda m: m.startswith("openai/"),
        "build": lambda self, model: _filter_none({
            "model": model,
            "api_key": os.getenv("OPENAI_API_KEY"),
            "api_base": os.getenv("OPENAI_API_BASE") or None,
        }),
    },
    "openrouter": {
        "label": "OpenRouter",
        "models": [
            {"id": "openrouter/anthropic/claude-3.5-sonnet", "label": "Claude 3.5 Sonnet"},
            {"id": "openrouter/google/gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
            {"id": "openrouter/meta-llama/llama-3.3-70b-instruct", "label": "Llama 3.3 70B"},
            {"id": "openrouter/mistralai/mistral-large", "label": "Mistral Large"},
            {"id": "openrouter/deepseek/deepseek-chat", "label": "DeepSeek Chat (via OpenRouter)"},
        ],
        "free_text_model": True,
        "env_keys": [
            {"key": "OPENROUTER_API_KEY", "label": "OpenRouter API Key", "secret": True, "placeholder": "sk-or-…"},
        ],
        "match": lambda m: m.startswith("openrouter/"),
        "build": lambda self, model: {
            "model": model,
            "api_key": os.getenv("OPENROUTER_API_KEY"),
            "api_base": os.getenv("OPENROUTER_API_BASE") or "https://openrouter.ai/api/v1",
        },
    },
    "azure": {
        "label": "Azure AI Foundry (Azure OpenAI)",
        "models": [],
        "free_text_model": True,
        "model_hint": "azure/<your-deployment-name>",
        "env_keys": [
            {"key": "AZURE_API_KEY", "label": "Azure API Key", "secret": True, "placeholder": "Azure resource key"},
            {"key": "AZURE_API_BASE", "label": "Azure Endpoint URL", "secret": False, "placeholder": "https://<resource>.openai.azure.com/"},
            {"key": "AZURE_API_VERSION", "label": "API Version", "secret": False, "placeholder": "2024-10-21"},
        ],
        "match": lambda m: m.startswith("azure/"),
        "build": lambda self, model: {
            "model": model,
            "api_key": os.getenv("AZURE_API_KEY"),
            "api_base": os.getenv("AZURE_API_BASE"),
            "api_version": os.getenv("AZURE_API_VERSION") or "2024-10-21",
        },
    },
    "azure_ai": {
        "label": "Azure AI Foundry (Models as a Service)",
        "models": [
            {"id": "azure_ai/Mistral-Large-2411", "label": "Mistral Large 2411"},
            {"id": "azure_ai/Meta-Llama-3.3-70B-Instruct", "label": "Llama 3.3 70B Instruct"},
            {"id": "azure_ai/Phi-4", "label": "Phi-4"},
        ],
        "free_text_model": True,
        "model_hint": "azure_ai/<model-id-from-Foundry>",
        "env_keys": [
            {"key": "AZURE_AI_API_KEY", "label": "Azure AI API Key", "secret": True, "placeholder": "Foundry endpoint key"},
            {"key": "AZURE_AI_API_BASE", "label": "Azure AI Endpoint URL", "secret": False, "placeholder": "https://<resource>.services.ai.azure.com/models/"},
        ],
        "match": lambda m: m.startswith("azure_ai/"),
        "build": lambda self, model: {
            "model": model,
            "api_key": os.getenv("AZURE_AI_API_KEY"),
            "api_base": os.getenv("AZURE_AI_API_BASE"),
        },
    },
}

# Order in which prefix resolution is attempted. Most specific first.
_PROVIDER_ORDER = ["openrouter", "azure_ai", "azure", "openai", "deepseek"]

_PLACEHOLDER_VALUES = {"", None, "sk-your-key-here", "your-key-here"}

# Transient HTTP statuses worth retrying with exponential backoff.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_RETRIES = 3


def _filter_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def resolve_provider(model_name: str) -> str:
    """Return the provider id for a given litellm model string."""
    m = (model_name or "").strip()
    for pid in _PROVIDER_ORDER:
        cfg = PROVIDERS.get(pid)
        if cfg and cfg["match"](m):
            return pid
    # Bare OpenAI-style names (gpt-4o, gpt-4.1-mini, ...) → OpenAI.
    return "openai"


def get_llm_catalog() -> dict:
    """Provider catalog safe to expose to the frontend.

    Includes which env keys are configured (boolean only — never the value)
    so the UI can show a checkmark next to keys that are already set.
    Merges fetched models from DB cache when available."""
    fetched = _load_fetched_models()
    catalog = {}
    for pid, cfg in PROVIDERS.items():
        merged_models = list(cfg["models"])
        if pid in fetched and fetched[pid]:
            existing_ids = {m["id"] for m in merged_models}
            for fm in fetched[pid]:
                if fm.get("id") and fm["id"] not in existing_ids:
                    merged_models.append(fm)
        catalog[pid] = {
            "label": cfg["label"],
            "models": merged_models,
            "free_text_model": cfg.get("free_text_model", False),
            "model_hint": cfg.get("model_hint"),
            "env_keys": [
                {
                    "key": ek["key"],
                    "label": ek["label"],
                    "secret": ek["secret"],
                    "placeholder": ek["placeholder"],
                    "is_set": bool(os.getenv(ek["key"]))
                    and os.getenv(ek["key"]) not in _PLACEHOLDER_VALUES,
                }
                for ek in cfg["env_keys"]
            ],
        }
    catalog["current_provider"] = resolve_provider(
        os.getenv("DEFAULT_MODEL") or DEFAULT_MODEL
    )
    return catalog


# ── Live model fetching ──────────────────────────────────────────────

_FETCHED_MODELS_CACHE: dict = {}

_PLACEHOLDER_KEYS = {"", None, "sk-your-key-here", "your-key-here"}


def _load_fetched_models() -> dict:
    """Load previously fetched model lists from the DB settings store."""
    global _FETCHED_MODELS_CACHE
    if _FETCHED_MODELS_CACHE:
        return _FETCHED_MODELS_CACHE
    try:
        from .database import SessionLocal, SettingsRecord
        db = SessionLocal()
        row = db.query(SettingsRecord).filter(SettingsRecord.key == "LLM_FETCHED_MODELS").first()
        db.close()
        if row and row.value:
            _FETCHED_MODELS_CACHE = json.loads(row.value)
    except Exception:
        pass
    return _FETCHED_MODELS_CACHE


def _save_fetched_models(data: dict):
    """Persist fetched model lists to the DB settings store."""
    global _FETCHED_MODELS_CACHE
    _FETCHED_MODELS_CACHE = data
    try:
        from .database import SessionLocal, SettingsRecord
        db = SessionLocal()
        row = db.query(SettingsRecord).filter(SettingsRecord.key == "LLM_FETCHED_MODELS").first()
        if row:
            row.value = json.dumps(data)
        else:
            db.add(SettingsRecord(key="LLM_FETCHED_MODELS", value=json.dumps(data)))
        db.commit()
        db.close()
    except Exception as e:
        print(f"[llm] failed to save fetched models: {e}")


async def _fetch_openai_models(api_key: str, base: str | None) -> list[dict]:
    """Fetch GPT-family models from an OpenAI-compatible endpoint."""
    url = f"{base or 'https://api.openai.com/v1'}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=15) as cli:
        resp = await cli.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        # Filter to relevant chat/instruction models
        if any(p in mid.lower() for p in ("gpt-", "o1", "o3", "o4", "claude", "gemini", "deepseek-")):
            models.append({"id": mid, "label": mid})
    return sorted(models, key=lambda x: x["id"])


async def fetch_live_models() -> dict:
    """Query each configured provider for its currently available models.
    Returns {provider_id: [{id, label}, …], …}.  Only providers with a valid
    API key are queried; the rest are left with their preset defaults."""
    results: dict = {}

    # ── DeepSeek (OpenAI-compatible surface) ──
    ds_key = os.getenv("DEEPSEEK_API_KEY")
    if ds_key and ds_key not in _PLACEHOLDER_KEYS:
        try:
            results["deepseek"] = await _fetch_openai_models(ds_key, "https://api.deepseek.com/v1")
        except Exception as e:
            print(f"[llm] fetch deepseek models error: {e}")

    # ── OpenAI ──
    oai_key = os.getenv("OPENAI_API_KEY")
    if oai_key and oai_key not in _PLACEHOLDER_KEYS:
        try:
            results["openai"] = await _fetch_openai_models(oai_key, os.getenv("OPENAI_API_BASE") or None)
        except Exception as e:
            print(f"[llm] fetch openai models error: {e}")

    # ── OpenRouter ──
    or_key = os.getenv("OPENROUTER_API_KEY")
    if or_key and or_key not in _PLACEHOLDER_KEYS:
        try:
            async with httpx.AsyncClient(timeout=20) as cli:
                resp = await cli.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {or_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
            or_models = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                label = m.get("name", mid)
                if mid and not mid.startswith("openrouter/"):
                    mid = f"openrouter/{mid}"
                or_models.append({"id": mid, "label": label})
            results["openrouter"] = sorted(or_models, key=lambda x: x["label"].lower())
        except Exception as e:
            print(f"[llm] fetch openrouter models error: {e}")

    # Persist
    if results:
        _save_fetched_models(results)
    return results


class LLMManager:
    """Thin wrapper around litellm that routes to any configured provider.

    The provider is determined by the *model string's prefix* (or, for
    DeepSeek, by a known model-id set). Each provider entry in PROVIDERS
    knows which env vars to read and how to assemble the litellm kwargs.
    """

    def __init__(self, model_name: str = None):
        raw = (model_name or os.getenv("DEFAULT_MODEL") or DEFAULT_MODEL).strip()
        # Tolerate legacy "deepseek/<model>" litellm-prefix values from settings.
        if raw.startswith("deepseek/"):
            raw = raw.split("/", 1)[-1]
        self.model_name = raw
        self.provider = resolve_provider(raw)
        self.provider_cfg = PROVIDERS[self.provider]

        # is_mock = primary key for the resolved provider is missing.
        primary_key = self.provider_cfg["env_keys"][0]["key"]
        self.api_key = os.getenv(primary_key)
        self.is_mock = self.api_key in _PLACEHOLDER_VALUES

    # ── public API ─────────────────────────────────────────────

    async def analyze(self, prompt: str, json_schema: dict = None) -> dict:
        if self.is_mock:
            await asyncio.sleep(1.5)
            return self._get_mock_response(prompt)

        json_mode = json_schema is not None
        messages = [{"role": "user", "content": prompt}]
        kwargs = self._build_kwargs(messages, json_mode)

        last_err = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await acompletion(**kwargs)
                content = response.choices[0].message.content
                if not content or not content.strip():
                    # Some providers occasionally return empty JSON Output
                    # content. Retry with the same prompt instead of crashing.
                    raise ValueError("model returned empty content")
                return self._parse_json(content)
            except Exception as e:
                last_err = e
                status = getattr(e, "status_code", None) or getattr(
                    getattr(e, "response", None), "status_code", None
                )
                retryable = status in _RETRYABLE_STATUS or isinstance(
                    e, (asyncio.TimeoutError, ConnectionError)
                )
                print(
                    f"[llm] {self.provider}/{self.model_name} "
                    f"attempt {attempt + 1}/{_MAX_RETRIES} error (status={status}): {e}"
                )
                if attempt < _MAX_RETRIES - 1 and (retryable or status is None):
                    await asyncio.sleep(2 ** attempt)
                elif not retryable:
                    break

        print(f"[llm] giving up, falling back to mock. last error: {last_err}")
        return self._get_mock_response(prompt)

    # ── helpers ────────────────────────────────────────────────

    def _build_kwargs(self, messages, json_mode) -> dict:
        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": 1024,
        }
        # Provider-specific routing (api_key / api_base / custom provider /
        # thinking-disabled etc.) comes from the catalog's build() lambda.
        kwargs.update(self.provider_cfg["build"](self, self.model_name))
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        # Tolerate code-fenced JSON ```json ... ``` just in case.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)

    # ── offline fallback ───────────────────────────────────────

    def _get_mock_response(self, prompt: str) -> dict:
        text = str(prompt).lower()
        if "triage" in text or "analyze the following it support ticket" in text:
            if "vpn" in text:
                return {
                    "sentiment": "Business-Critical",
                    "category": "Network",
                    "priority": "P1",
                    "mood": "urgent",
                    "action": "escalate",
                    "reasoning": "VPN instability is affecting business operations. Needs immediate attention.",
                }
            if "database" in text or "production" in text:
                return {
                    "sentiment": "Business-Critical",
                    "category": "Software",
                    "priority": "P1",
                    "mood": "critical",
                    "action": "escalate",
                    "reasoning": "Critical production outage. Immediate escalation required.",
                }
            if "password" in text or "access" in text:
                return {
                    "sentiment": "Neutral",
                    "category": "Access Request",
                    "priority": "P3",
                    "mood": "concerned",
                    "action": "respond",
                    "reasoning": "Standard access request. Can be handled with self-service guidance.",
                }
            return {
                "sentiment": "Neutral",
                "category": "Other",
                "priority": "P3",
                "mood": "neutral",
                "action": "respond",
                "reasoning": "Standard support request. Straightforward to resolve.",
            }
        elif "draft a professional" in text or "reply_prompt" in text.lower():
            return {
                "suggested_response": "Thank you for reaching out. We've reviewed your request and are working on it. We'll get back to you with an update shortly."
            }
        return {
            "sentiment": "Neutral",
            "category": "Other",
            "priority": "P3",
            "mood": "neutral",
            "action": "respond",
            "reasoning": "Mock response.",
        }