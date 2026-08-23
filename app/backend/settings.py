import os
import re
import sys
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
    "FOUNDRY_API_KEY",
    "CUSTOM_API_KEY",
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
    "your-foundry-key-here",
    "your-custom-key-here",
}

_ALL_KEYS = [
    # Runtime mode / security
    "APP_MODE",
    "TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED",
    "SEED_DEMO_DATA",
    "CORS_ALLOW_ORIGINS",
    "COOKIE_SECURE",
    "COOKIE_SAMESITE",
    "LLM_ALLOW_PRIVATE_ENDPOINTS",
    "LLM_ALLOW_INSECURE_ENDPOINTS",
    "LLM_ALLOWED_PROVIDER_HOSTS",
    # Deliberately small LLM surface: Microsoft Foundry plus one custom API.
    "FOUNDRY_API_KEY",
    "FOUNDRY_API_BASE",
    "FOUNDRY_AUTH_METHOD",
    "CUSTOM_API_KEY",
    "CUSTOM_API_BASE",
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
    "TICKET_RAG_SCOPE_KEY",
    "TICKET_RAG_V2_SCOPE_ALLOWLIST",
    "TICKET_RAG_V2_WRITE_ENABLED",
    "TICKET_RAG_V2_WORKER_ENABLED",
    "TICKET_RAG_V2_READ_ENABLED",
    "TICKET_RAG_CHUNK_TARGET_TOKENS",
    "TICKET_RAG_CHUNK_MAX_TOKENS",
    "TICKET_RAG_CHUNK_OVERLAP_TOKENS",
    "TICKET_RAG_EMBED_BATCH_SIZE",
    "TICKET_RAG_EMBED_LEASE_SECONDS",
    "TICKET_RAG_WORKER_POLL_SECONDS",
    "TICKET_RAG_QUERY_CACHE_TTL_SECONDS",
    "TICKET_RAG_QUERY_CACHE_MAX_ROWS",
    "TICKET_RAG_SNAPSHOT_TTL_SECONDS",
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
    "TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED",
    "SEED_DEMO_DATA",
    "DATABASE_URL",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    "LLM_ALLOW_PRIVATE_ENDPOINTS",
    "LLM_ALLOW_INSECURE_ENDPOINTS",
    "LLM_ALLOWED_PROVIDER_HOSTS",
    "WEBHOOK_MAX_AGE_SECONDS",
    "TICKET_RAG_SCOPE_KEY",
    "TICKET_RAG_V2_SCOPE_ALLOWLIST",
}

_LLM_BASE_URL_KEYS = {
    "FOUNDRY_API_BASE",
    "CUSTOM_API_BASE",
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
    "FOUNDRY_AUTH_METHOD",
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
    "TICKET_RAG_V2_WRITE_ENABLED",
    "TICKET_RAG_V2_WORKER_ENABLED",
    "TICKET_RAG_V2_READ_ENABLED",
    "TICKET_RAG_CHUNK_TARGET_TOKENS",
    "TICKET_RAG_CHUNK_MAX_TOKENS",
    "TICKET_RAG_CHUNK_OVERLAP_TOKENS",
    "TICKET_RAG_EMBED_BATCH_SIZE",
    "TICKET_RAG_EMBED_LEASE_SECONDS",
    "TICKET_RAG_WORKER_POLL_SECONDS",
    "TICKET_RAG_QUERY_CACHE_TTL_SECONDS",
    "TICKET_RAG_QUERY_CACHE_MAX_ROWS",
    "TICKET_RAG_SNAPSHOT_TTL_SECONDS",
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

# A production administrator may opt in to editing operational/provider
# settings through the portal. Infrastructure trust boundaries stay owned by
# the deployment even when the portal is enabled.
_PRODUCTION_INFRA_ONLY_KEYS = {
    "CORS_ALLOW_ORIGINS",
    "COOKIE_SECURE",
    "COOKIE_SAMESITE",
    "LOGIN_REQUIRED",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_PROJECT_KEY",
    "JIRA_ISSUE_TYPE",
    "SSO_ENABLED",
    "SSO_PROVIDER",
    "SSO_CLIENT_ID",
    "SSO_CLIENT_SECRET",
    "SSO_DISCOVERY_URL",
    "SSO_REDIRECT_URI",
    "SSO_ALLOWED_DOMAINS",
    "SSO_AUTO_PROVISION",
}
_PRODUCTION_ADMIN_PORTAL_KEYS = (
    _PRODUCTION_ENV_ONLY_KEYS - _PRODUCTION_INFRA_ONLY_KEYS - _READONLY_KEYS
)
_ADMIN_PORTAL_APPROVAL_PREFIX = "__ADMIN_PORTAL_APPROVED__:"

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
    if (os.getenv("APP_MODE") or "production").strip().lower() == "production":
        allowed_hosts = {
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


def _validate_foundry_base_url(value: str) -> str:
    """Accept only Microsoft Foundry OpenAI-compatible v1 endpoints."""
    normalized = _validate_llm_base_url(value)
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname.endswith((".services.ai.azure.com", ".openai.azure.com")):
        raise ValueError("Foundry endpoint must use a Microsoft Azure hostname")
    if parsed.path.rstrip("/") != "/openai/v1":
        raise ValueError("Foundry endpoint path must end with /openai/v1")
    return normalized


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
        return "production"
    mode = raw_mode.strip().lower()
    if mode not in {"demo", "production"}:
        raise ValueError("APP_MODE must be either 'demo' or 'production'")
    return mode


def is_demo_mode() -> bool:
    return app_mode() == "demo"


def is_production_mode() -> bool:
    return app_mode() == "production"


def admin_settings_portal_enabled() -> bool:
    """Whether production admin-approved DB overrides are enabled."""
    return get_bool("TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED", default=False)


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


def _read_portal_approved_keys() -> set[str]:
    """Return keys explicitly saved by an authenticated production admin."""
    db = SessionLocal()
    try:
        rows = db.query(SettingsRecord.key).filter(
            SettingsRecord.key.like(f"{_ADMIN_PORTAL_APPROVAL_PREFIX}%")
        ).all()
        return {
            key.removeprefix(_ADMIN_PORTAL_APPROVAL_PREFIX)
            for key, in rows
            if key.startswith(_ADMIN_PORTAL_APPROVAL_PREFIX)
        }
    except Exception:
        return set()
    finally:
        db.close()


def _write_db_overrides(
    updates: dict,
    *,
    actor_id: Optional[str] = None,
    approved_keys: Optional[set[str]] = None,
):
    db = SessionLocal()
    try:
        for key, value in updates.items():
            existing = db.query(SettingsRecord).filter(SettingsRecord.key == key).first()
            if existing:
                existing.value = value
            else:
                db.add(SettingsRecord(key=key, value=value))
        if actor_id:
            for key in sorted(approved_keys or set()):
                marker_key = f"{_ADMIN_PORTAL_APPROVAL_PREFIX}{key}"
                marker = db.query(SettingsRecord).filter(
                    SettingsRecord.key == marker_key
                ).first()
                if marker:
                    marker.value = actor_id
                else:
                    db.add(SettingsRecord(key=marker_key, value=actor_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def load_settings_into_env() -> bool:
    """At startup, hydrate os.environ with DB-stored overrides so every
    module that reads env once at import time still sees the saved values."""
    global _loaded
    with _lock:
        overrides = _read_db_overrides()
        production = is_production_mode()
        portal_enabled = production and admin_settings_portal_enabled()
        approved_keys = _read_portal_approved_keys() if portal_enabled else set()
        changed = False
        for key, value in overrides.items():
            if key not in _ALL_KEYS or key in _READONLY_KEYS:
                continue
            if production and key in _PRODUCTION_ENV_ONLY_KEYS and not (
                portal_enabled
                and key in _PRODUCTION_ADMIN_PORTAL_KEYS
                and key in approved_keys
            ):
                continue
            if value is not None:
                if key in _LLM_BASE_URL_KEYS and value:
                    value = _validate_llm_base_url(value)
                changed = changed or os.getenv(key) != value
                os.environ[key] = value
        validate_effective_llm_urls()
        _loaded = True
        return changed


def validate_effective_llm_urls() -> None:
    """Validate DB and process-environment destinations before any AI I/O."""
    for key in _LLM_BASE_URL_KEYS:
        value = (os.getenv(key) or "").strip()
        if value:
            os.environ[key] = (
                _validate_foundry_base_url(value)
                if key == "FOUNDRY_API_BASE"
                else _validate_llm_base_url(value)
            )
    from .llm_manager import foundry_auth_method, resolve_provider

    foundry_auth_method()
    default_model = (os.getenv("DEFAULT_MODEL") or "").strip()
    if default_model:
        resolve_provider(default_model)
    embedding_model = (os.getenv("TICKET_EMBEDDING_MODEL") or "").strip()
    if embedding_model:
        resolve_provider(embedding_model)


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


def update_settings(payload: dict, *, actor_id: Optional[str] = None) -> dict:
    with _lock:
        production = is_production_mode()
        portal_enabled = production and admin_settings_portal_enabled()
        base_url_credentials = {
            "FOUNDRY_API_BASE": "FOUNDRY_API_KEY",
            "CUSTOM_API_BASE": "CUSTOM_API_KEY",
        }
        for base_key, credential_key in base_url_credentials.items():
            if base_key not in payload:
                continue
            if base_key == "FOUNDRY_API_BASE" and str(
                payload.get("FOUNDRY_AUTH_METHOD")
                or os.getenv("FOUNDRY_AUTH_METHOD")
                or "api_key"
            ).strip().lower() == "entra":
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
            if key not in payload or key in _READONLY_KEYS:
                continue
            if production and key in _PRODUCTION_ENV_ONLY_KEYS and not (
                portal_enabled
                and bool(actor_id)
                and key in _PRODUCTION_ADMIN_PORTAL_KEYS
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
                new_val = (
                    _validate_foundry_base_url(new_val)
                    if key == "FOUNDRY_API_BASE"
                    else _validate_llm_base_url(new_val)
                )
            if key in {"DEFAULT_MODEL", "TICKET_EMBEDDING_MODEL"}:
                from .llm_manager import resolve_provider

                resolve_provider(new_val)
            if key == "FOUNDRY_AUTH_METHOD" and new_val not in {"api_key", "entra"}:
                raise ValueError("FOUNDRY_AUTH_METHOD must be 'api_key' or 'entra'")
            if key == "FRESHSERVICE_OAUTH_SCOPES" and new_val:
                from .integrations.freshservice import FreshserviceAdapter

                new_val = FreshserviceAdapter._validate_oauth_scopes(new_val)
            updates[key] = new_val

        if updates:
            approved_keys = {
                key
                for key in updates
                if production and key in _PRODUCTION_ADMIN_PORTAL_KEYS
            }
            if actor_id or approved_keys:
                _write_db_overrides(
                    updates,
                    actor_id=actor_id,
                    approved_keys=approved_keys,
                )
            else:
                _write_db_overrides(updates)
            for key, value in updates.items():
                os.environ[key] = value

    if updates:
        _reset_runtime()
    return get_settings()


def refresh_settings_from_db() -> bool:
    """Apply newly admin-approved overrides in long-running worker processes."""
    changed = load_settings_into_env()
    if changed:
        _reset_runtime(restart_scheduler=False)
    return changed


def _reset_runtime(*, restart_scheduler: bool = True):
    """Reset cached adapters and restart sync worker to pick up new env values."""
    try:
        from . import llm_manager

        llm_manager.invalidate_model_catalog_refresh()
    except Exception as e:
        print(f"[settings] invalidate model catalog error kind={type(e).__name__}")

    try:
        from .integrations import registry
        registry._ADAPTERS.clear()
    except Exception as e:
        print(f"[settings] clear adapters error kind={type(e).__name__}")

    if restart_scheduler:
        try:
            from . import sync_worker
            sync_worker.stop_sync_worker()
            sync_worker.start_sync_worker()
        except Exception as e:
            print(f"[settings] restart sync worker error kind={type(e).__name__}")

    try:
        main_module = sys.modules.get("app.backend.main")
        if main_module is not None:
            main_module.llm_mgr = main_module.LLMManager()
            main_module.engine.llm = main_module.llm_mgr
    except Exception as e:
        print(f"[settings] reset llm manager error kind={type(e).__name__}")
