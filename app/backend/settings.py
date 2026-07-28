import os
import math
import re
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
    "DATABASE_URL",
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
    "LLM_ALLOWED_PROVIDER_HOSTS",
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
    "ANALYTICS_USER_REQUESTS_PER_MINUTE",
    "ANALYTICS_USER_REQUESTS_PER_DAY",
    "AI_INDEX_WRITES_PER_MINUTE",
    "AI_INDEX_WRITES_PER_DAY",
    "PORTAL_TICKETS_PER_MINUTE",
    "PORTAL_TICKETS_PER_DAY",
    "PORTAL_TICKETS_GLOBAL_PER_MINUTE",
    "PORTAL_TICKETS_GLOBAL_PER_DAY",
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
    "WEBHOOK_MAX_AGE_SECONDS",
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
    "LLM_ALLOWED_PROVIDER_HOSTS",
    "WEBHOOK_MAX_AGE_SECONDS",
}

_LLM_BASE_URL_KEYS = {
    "OPENAI_API_BASE",
    "OPENROUTER_API_BASE",
    "AZURE_API_BASE",
    "AZURE_AI_API_BASE",
    "CUSTOM_API_BASE",
    "TICKET_EMBEDDING_API_BASE",
}

_PRODUCTION_ENV_ONLY_KEYS = (
    _SENSITIVE_KEYS
    - {"FRESHSERVICE_OAUTH_ACCESS_TOKEN", "FRESHSERVICE_OAUTH_REFRESH_TOKEN"}
) | _LLM_BASE_URL_KEYS | {
    "CORS_ALLOW_ORIGINS",
    "COOKIE_SECURE",
    "COOKIE_SAMESITE",
    "WEBHOOK_MAX_AGE_SECONDS",
    "LOGIN_REQUIRED",
    "DEFAULT_MODEL",
    "CUSTOM_PROVIDER_TYPE",
    "CUSTOM_API_VERSION",
    "CUSTOM_TEMPERATURE",
    "CUSTOM_MAX_TOKENS",
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
    "ANALYTICS_USER_REQUESTS_PER_MINUTE",
    "ANALYTICS_USER_REQUESTS_PER_DAY",
    "AI_INDEX_WRITES_PER_MINUTE",
    "AI_INDEX_WRITES_PER_DAY",
    "PORTAL_TICKETS_PER_MINUTE",
    "PORTAL_TICKETS_PER_DAY",
    "PORTAL_TICKETS_GLOBAL_PER_MINUTE",
    "PORTAL_TICKETS_GLOBAL_PER_DAY",
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
    "AUTO_TRIAGE_ENABLED",
    "AUTO_SUMMARIZE_ENABLED",
    "AUTO_ROUTE_ENABLED",
    "AUTO_RESOLVE_ENABLED",
    "AUTO_SYSTEMIC_ENABLED",
    "ITSM_PROVIDER",
    "FRESHSERVICE_DOMAIN",
    "FRESHWORKS_ORG_DOMAIN",
    "FRESHSERVICE_WORKSPACE_ID",
    "FRESHSERVICE_TICKET_INCLUDES",
    "FRESHSERVICE_AGENT_STATE",
    "FRESHSERVICE_OAUTH_CLIENT_ID",
    "FRESHSERVICE_OAUTH_REDIRECT_URI",
    "FRESHSERVICE_OAUTH_SCOPES",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_PROJECT_KEY",
    "JIRA_ISSUE_TYPE",
    "SYNC_INTERVAL_SECONDS",
    "SSO_ENABLED",
    "SSO_PROVIDER",
    "SSO_CLIENT_ID",
    "SSO_CLIENT_SECRET",
    "SSO_DISCOVERY_URL",
    "SSO_REDIRECT_URI",
    "SSO_ALLOWED_DOMAINS",
    "SSO_AUTO_PROVISION",
}

_lock = threading.Lock()
_loaded = False


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _validate_llm_base_url(value: str) -> str:
    if not value or value != value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError("LLM base URL contains invalid whitespace or control characters")
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("LLM base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("LLM base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("LLM base URL must not contain a query string or fragment")
    if parsed.scheme != "https" and not _truthy(os.getenv("LLM_ALLOW_INSECURE_ENDPOINTS")):
        raise ValueError("LLM base URL must use HTTPS")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("LLM base URL contains an invalid port") from exc
    if (
        port not in {None, 443}
        and not _truthy(os.getenv("LLM_ALLOW_INSECURE_ENDPOINTS"))
    ):
        raise ValueError("LLM base URL must use the standard HTTPS port")

    hostname = parsed.hostname.lower().rstrip(".")
    if (os.getenv("APP_MODE") or "demo").strip().lower() == "production":
        allowed_hosts = {
            "api.openai.com",
            "openrouter.ai",
            "api.deepseek.com",
            *{
                host.strip().lower().rstrip(".")
                for host in (os.getenv("LLM_ALLOWED_PROVIDER_HOSTS") or "").split(",")
                if host.strip()
            },
        }
        if hostname not in allowed_hosts:
            raise ValueError("LLM base URL hostname is not in LLM_ALLOWED_PROVIDER_HOSTS")
    if _truthy(os.getenv("LLM_ALLOW_PRIVATE_ENDPOINTS")):
        return value.rstrip("/")
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
    raw_mode = os.getenv("APP_MODE")
    if raw_mode is None or not raw_mode.strip():
        return "demo"
    mode = raw_mode.strip().lower()
    if mode not in {"demo", "production"}:
        raise ValueError("APP_MODE must be either 'demo' or 'production'")
    return mode


def is_demo_mode() -> bool:
    return app_mode() == "demo"


def is_production_mode() -> bool:
    return app_mode() == "production"


def automation_enabled(key: str, legacy_alias: Optional[str] = None) -> bool:
    """Return whether an automatic AI workflow is explicitly enabled.

    Demo installations may use real providers, but background automation is
    only safe once the demo is access-controlled.  Explicitly queued work is
    handled separately by the worker and intentionally does not use this
    gate.
    """
    aliases = (legacy_alias,) if legacy_alias else ()
    if not get_bool(key, default=False, aliases=aliases):
        return False
    return not is_demo_mode() or get_bool("LOGIN_REQUIRED", default=False)


def _mask(value: Optional[str]) -> str:
    if not value:
        return ""
    if value in _PLACEHOLDER_VALUES:
        return ""
    return "****"


def _read_db_overrides() -> dict:
    """Return settings overrides stored in DB (key -> value)."""
    db = SessionLocal()
    try:
        # SettingsRecord also carries bounded internal state. Never turn an
        # arbitrary or legacy row into a process environment variable.
        rows = db.query(SettingsRecord).filter(SettingsRecord.key.in_(_ALL_KEYS)).all()
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
            if key not in _ALL_KEYS or key in _READONLY_KEYS or (
                is_production_mode() and key in _PRODUCTION_ENV_ONLY_KEYS
            ):
                continue
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
        base_url_credentials = {
            "OPENAI_API_BASE": "OPENAI_API_KEY",
            "OPENROUTER_API_BASE": "OPENROUTER_API_KEY",
            "AZURE_API_BASE": "AZURE_API_KEY",
            "AZURE_AI_API_BASE": "AZURE_AI_API_KEY",
            "CUSTOM_API_BASE": "CUSTOM_API_KEY",
        }
        embedding_model = (os.getenv("TICKET_EMBEDDING_MODEL") or "").strip()
        if embedding_model.startswith("openai/"):
            base_url_credentials["TICKET_EMBEDDING_API_BASE"] = "OPENAI_API_KEY"
        elif embedding_model.startswith("custom/"):
            base_url_credentials["TICKET_EMBEDDING_API_BASE"] = "CUSTOM_API_KEY"
        for base_key, credential_key in base_url_credentials.items():
            if base_key not in payload:
                continue
            proposed_base = str(payload.get(base_key) or "").strip().rstrip("/")
            current_base = str(os.getenv(base_key) or "").strip().rstrip("/")
            if not proposed_base or "****" in proposed_base:
                continue
            current_credential = os.getenv(credential_key)
            replacement = payload.get(credential_key)
            replacement_is_real = (
                isinstance(replacement, str)
                and bool(replacement.strip())
                and "****" not in replacement
                and replacement.strip() not in _PLACEHOLDER_VALUES
            )
            if (
                proposed_base != current_base
                and current_credential
                and current_credential not in _PLACEHOLDER_VALUES
                and not replacement_is_real
            ):
                raise ValueError(
                    f"Changing {base_key} requires re-entering {credential_key}"
                )
        updates = {}
        for key in _ALL_KEYS:
            if key not in payload or key in _READONLY_KEYS or (
                is_production_mode() and key in _PRODUCTION_ENV_ONLY_KEYS
            ):
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
            if key == "CUSTOM_TEMPERATURE" and new_val:
                try:
                    temperature = float(new_val)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Custom temperature must be a number from 0 to 2") from exc
                if not math.isfinite(temperature) or not 0 <= temperature <= 2:
                    raise ValueError("Custom temperature must be a number from 0 to 2")
            if key == "CUSTOM_MAX_TOKENS" and new_val:
                try:
                    custom_max_tokens = int(new_val)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Custom max tokens must be an integer from 64 to 4096") from exc
                if not 64 <= custom_max_tokens <= 4096:
                    raise ValueError("Custom max tokens must be an integer from 64 to 4096")
            if key == "CUSTOM_PROVIDER_TYPE" and new_val and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", new_val
            ):
                raise ValueError("Custom provider type contains unsupported characters")
            updates[key] = new_val

        if updates:
            _write_db_overrides(updates)
            for key, value in updates.items():
                os.environ[key] = value
            _reset_runtime()

    return get_settings()


def _reset_runtime():
    """Reset cached adapters and restart sync worker to pick up new env values."""
    try:
        from .integrations import registry
        registry._ADAPTERS.clear()
    except Exception as e:
        print(f"[settings] clear adapters error kind={type(e).__name__}")

    try:
        from . import sync_worker
        sync_worker.stop_sync_worker()
        sync_worker.start_sync_worker()
    except Exception as e:
        print(f"[settings] restart sync worker error kind={type(e).__name__}")

    try:
        from . import main as main_module
        main_module.llm_mgr = main_module.LLMManager()
        main_module.engine.llm = main_module.llm_mgr
    except Exception as e:
        print(f"[settings] reset llm manager error kind={type(e).__name__}")
