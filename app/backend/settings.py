import os
import threading
from typing import Optional

from dotenv import load_dotenv

from .database import SessionLocal, SettingsRecord

load_dotenv()

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

_SENSITIVE_KEYS = {
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_BASE",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AZURE_API_VERSION",
    "AZURE_AI_API_KEY",
    "AZURE_AI_API_BASE",
    "FRESHSERVICE_API_KEY",
    "FRESHSERVICE_OAUTH_CLIENT_SECRET",
    "FRESHSERVICE_OAUTH_ACCESS_TOKEN",
    "FRESHSERVICE_OAUTH_REFRESH_TOKEN",
    "WEBHOOK_SECRET",
}

_PLACEHOLDER_VALUES = {
    "sk-your-key-here",
    "your-key-here",
    "your-freshservice-api-key",
    "your-webhook-secret",
    "your-azure-key-here",
    "your-azure-ai-key-here",
    "your-openrouter-key-here",
}

_ALL_KEYS = [
    # LLM provider keys (multi-provider; see llm_manager.PROVIDERS)
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_BASE",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AZURE_API_VERSION",
    "AZURE_AI_API_KEY",
    "AZURE_AI_API_BASE",
    "DEFAULT_MODEL",
    "DATABASE_URL",
    "ITSM_PROVIDER",
    "FRESHSERVICE_DOMAIN",
    "FRESHSERVICE_API_KEY",
    "FRESHSERVICE_OAUTH_CLIENT_ID",
    "FRESHSERVICE_OAUTH_CLIENT_SECRET",
    "FRESHSERVICE_OAUTH_REDIRECT_URI",
    "FRESHSERVICE_OAUTH_ACCESS_TOKEN",
    "FRESHSERVICE_OAUTH_REFRESH_TOKEN",
    "WEBHOOK_SECRET",
    "SYNC_INTERVAL_SECONDS",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    # AI automation toggles
    "SLA_P1_HOURS",
    "SLA_P2_HOURS",
    "SLA_P3_HOURS",
]

# Keys that are static infra config
_READONLY_KEYS = {
    "DATABASE_URL",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
}

_lock = threading.Lock()
_loaded = False


def _mask(value: Optional[str]) -> str:
    if not value:
        return ""
    if value in _PLACEHOLDER_VALUES:
        return ""
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


def _read_db_overrides() -> dict:
    """Return settings overrides stored in DB (key -> value)."""
    db = SessionLocal()
    try:
        rows = db.query(SettingsRecord).all()
        return {r.key: r.value for r in rows}
    except Exception:
        return {}
    finally:
        db.close()


def _write_db_overrides(updates: dict):
    db = SessionLocal()
    try:
        for key, value in updates.items():
            existing = db.query(SettingsRecord).filter(SettingsRecord.key == key).first()
            if existing:
                existing.value = value
            else:
                db.add(SettingsRecord(key=key, value=value))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def load_settings_into_env():
    """At startup, hydrate os.environ with DB-stored overrides so every
    module that reads env once at import time still sees the saved values."""
    global _loaded
    with _lock:
        overrides = _read_db_overrides()
        for key, value in overrides.items():
            if value is not None:
                os.environ[key] = value
        _loaded = True


def get_settings() -> dict:
    with _lock:
        result = {}
        for key in _ALL_KEYS:
            val = os.getenv(key, "")
            if key in _SENSITIVE_KEYS:
                result[key] = _mask(val)
                result[f"{key}__set"] = bool(val) and val not in _PLACEHOLDER_VALUES
            else:
                result[key] = val
        return result


def update_settings(payload: dict) -> dict:
    with _lock:
        updates = {}
        for key in _ALL_KEYS:
            if key not in payload or key in _READONLY_KEYS:
                continue
            new_val = payload.get(key)
            if new_val is None:
                continue
            if isinstance(new_val, str):
                new_val = new_val.strip()
            # Never accept a masked echo (e.g. "sk-5****") for a secret —
            # it's the redacted value we returned on GET, not a real key.
            # Skipping it preserves the previously stored value.
            if key in _SENSITIVE_KEYS and ("****" in new_val or new_val in _PLACEHOLDER_VALUES):
                continue
            if new_val == "":
                if key in _SENSITIVE_KEYS:
                    continue
                new_val = os.getenv(key, "")
            updates[key] = new_val
            os.environ[key] = new_val

        if updates:
            _write_db_overrides(updates)
            _reset_runtime()

    return get_settings()


def _reset_runtime():
    """Reset cached adapters and restart sync worker to pick up new env values."""
    try:
        from .integrations import registry
        registry._ADAPTERS.clear()
    except Exception as e:
        print(f"[settings] clear adapters error: {e}")

    try:
        from . import sync_worker
        sync_worker.stop_sync_worker()
        sync_worker.start_sync_worker()
    except Exception as e:
        print(f"[settings] restart sync worker error: {e}")

    try:
        from . import main as main_module
        main_module.llm_mgr = main_module.LLMManager()
        main_module.engine.llm = main_module.llm_mgr
    except Exception as e:
        print(f"[settings] reset llm manager error: {e}")