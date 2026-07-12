import os
import threading
import ipaddress
import socket
from urllib.parse import urlparse
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
    "CUSTOM_API_KEY",
    "CUSTOM_API_BASE",
    "FRESHSERVICE_API_KEY",
    "JIRA_API_TOKEN",
    "FRESHSERVICE_OAUTH_CLIENT_SECRET",
    "FRESHSERVICE_OAUTH_ACCESS_TOKEN",
    "FRESHSERVICE_OAUTH_REFRESH_TOKEN",
    "WEBHOOK_SECRET",
    "SSO_CLIENT_SECRET",
}

_PLACEHOLDER_VALUES = {
    "sk-your-key-here",
    "your-key-here",
    "your-provider-api-key",
    "your-webhook-secret",
    "your-azure-key-here",
    "your-azure-ai-key-here",
    "your-openrouter-key-here",
}

_ALL_KEYS = [
    # Runtime mode / security
    "APP_MODE",
    "SEED_DEMO_DATA",
    "CORS_ALLOW_ORIGINS",
    "COOKIE_SECURE",
    "COOKIE_SAMESITE",
    "LLM_ALLOW_PRIVATE_ENDPOINTS",
    "LLM_ALLOW_INSECURE_ENDPOINTS",
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
    "CUSTOM_API_KEY",
    "CUSTOM_API_BASE",
    "CUSTOM_PROVIDER_TYPE",
    "CUSTOM_API_VERSION",
    "CUSTOM_TEMPERATURE",
    "CUSTOM_MAX_TOKENS",
    "DEFAULT_MODEL",
    "LLM_ALLOW_SYNTHETIC",
    "LLM_REQUEST_TIMEOUT_SECONDS",
    "LLM_OVERALL_TIMEOUT_SECONDS",
    "LLM_MAX_PROMPT_CHARS",
    "LLM_MAX_CONCURRENCY",
    "LLM_PERSIST_METRICS",
    "LLM_DAILY_TOKEN_BUDGET",
    "LLM_PROVIDER_REQUESTS_PER_MINUTE",
    "LLM_PROVIDER_TOKENS_PER_MINUTE",
    "LLM_ENFORCE_PROVIDER_LIMITS",
    "AI_USER_REQUESTS_PER_MINUTE",
    "AI_USER_REQUESTS_PER_DAY",
    "AI_ANALYSIS_LEASE_SECONDS",
    "AI_ANALYSIS_MAX_ATTEMPTS",
    "AI_PIPELINE_TIMEOUT_SECONDS",
    "TICKET_EMBEDDING_ENABLED",
    "TICKET_EMBEDDING_MODEL",
    "TICKET_EMBEDDING_DIMENSIONS",
    "TICKET_EMBEDDING_TIMEOUT_SECONDS",
    "TICKET_EMBEDDING_MAX_CHARS",
    "TICKET_EMBEDDING_MAX_COMMENTS_PER_REFRESH",
    "TICKET_VECTOR_MIN_SCORE",
    "TICKET_EMBEDDING_API_BASE",
    "DATABASE_URL",
    "ITSM_PROVIDER",
    "FRESHSERVICE_DOMAIN",
    "FRESHWORKS_ORG_DOMAIN",
    "FRESHSERVICE_API_KEY",
    "FRESHSERVICE_WORKSPACE_ID",
    "FRESHSERVICE_TICKET_INCLUDES",
    "FRESHSERVICE_AGENT_STATE",
    "FRESHSERVICE_OAUTH_CLIENT_ID",
    "FRESHSERVICE_OAUTH_CLIENT_SECRET",
    "FRESHSERVICE_OAUTH_REDIRECT_URI",
    "FRESHSERVICE_OAUTH_SCOPES",
    "FRESHSERVICE_OAUTH_ACCESS_TOKEN",
    "FRESHSERVICE_OAUTH_REFRESH_TOKEN",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_PROJECT_KEY",
    "JIRA_ISSUE_TYPE",
    "WEBHOOK_SECRET",
    "SYNC_INTERVAL_SECONDS",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    "FRONTEND_URL",
    # AI automation toggles
    "SLA_P1_HOURS",
    "SLA_P2_HOURS",
    "SLA_P3_HOURS",
    "SLA_P4_HOURS",
    # Organization / branding
    "ORG_NAME",
    "ORG_LOGO_URL",
    "ORG_PRIMARY_COLOR",
    # AI automation toggles
    "AUTO_TRIAGE_ENABLED",
    "AUTO_SUMMARIZE_ENABLED",
    "AUTO_ROUTE_ENABLED",
    "AUTO_RESOLVE_ENABLED",
    "AUTO_SYSTEMIC_ENABLED",
    # Auth / Security
    "LOGIN_REQUIRED",
    "SSO_ENABLED",
    "SSO_PROVIDER",
    "SSO_CLIENT_ID",
    "SSO_CLIENT_SECRET",
    "SSO_DISCOVERY_URL",
    "SSO_REDIRECT_URI",
    "SSO_ALLOWED_DOMAINS",
    "SSO_AUTO_PROVISION",
]

# Keys that are static infra config
_READONLY_KEYS = {
    "APP_MODE",
    "SEED_DEMO_DATA",
    "DATABASE_URL",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    "LLM_ALLOW_PRIVATE_ENDPOINTS",
    "LLM_ALLOW_INSECURE_ENDPOINTS",
}

_LLM_BASE_URL_KEYS = {
    "OPENAI_API_BASE",
    "OPENROUTER_API_BASE",
    "AZURE_API_BASE",
    "AZURE_AI_API_BASE",
    "CUSTOM_API_BASE",
    "TICKET_EMBEDDING_API_BASE",
}

_lock = threading.Lock()
_loaded = False


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _validate_llm_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("LLM base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("LLM base URL must not contain credentials")
    if parsed.scheme != "https" and not _truthy(os.getenv("LLM_ALLOW_INSECURE_ENDPOINTS")):
        raise ValueError("LLM base URL must use HTTPS")

    if _truthy(os.getenv("LLM_ALLOW_PRIVATE_ENDPOINTS")):
        return value.rstrip("/")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("LLM base URL must not target a local hostname")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("LLM base URL hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("LLM base URL must not target a private or reserved address")
    return value.rstrip("/")


def get_bool(key: str, default: bool = False, aliases: tuple[str, ...] = ()) -> bool:
    """Read an env-style boolean with optional legacy aliases."""
    for candidate in (key, *aliases):
        value = os.getenv(candidate)
        if value is not None and value != "":
            return _truthy(value)
    return default


def app_mode() -> str:
    mode = os.getenv("APP_MODE", "demo").strip().lower()
    return mode if mode in {"demo", "production"} else "demo"


def is_demo_mode() -> bool:
    return app_mode() == "demo"


def is_production_mode() -> bool:
    return app_mode() == "production"


def automation_enabled(key: str, legacy_alias: Optional[str] = None) -> bool:
    """AI automation defaults on in demo, off in production unless enabled."""
    aliases = (legacy_alias,) if legacy_alias else ()
    return get_bool(key, default=is_demo_mode(), aliases=aliases)


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
                if key in _LLM_BASE_URL_KEYS and value:
                    value = _validate_llm_base_url(value)
                os.environ[key] = value
        validate_effective_llm_urls()
        _loaded = True


def validate_effective_llm_urls() -> None:
    """Validate DB and process-environment destinations before any AI I/O."""
    for key in _LLM_BASE_URL_KEYS:
        value = (os.getenv(key) or "").strip()
        if value:
            os.environ[key] = _validate_llm_base_url(value)


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
            if key in _LLM_BASE_URL_KEYS and new_val:
                new_val = _validate_llm_base_url(new_val)
            if key == "DEFAULT_MODEL":
                from .llm_manager import resolve_provider

                resolve_provider(new_val)
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
