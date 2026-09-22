import os
import re
import sys
import threading
import hmac
import ipaddress
import socket
import uuid
import base64
import binascii
import json
from urllib.parse import urlparse
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv
from sqlalchemy import text

from .database import SessionLocal, SettingsRecord
from .email_service import normalize_email_address, normalize_sender_name

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
    "AZURE_STORAGE_CONNECTION_STRING",
    "SENDGRID_API_KEY",
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
    "CORS_ALLOW_ORIGINS",
    "COOKIE_SECURE",
    "COOKIE_SAMESITE",
    # Session storage is deployment-owned so a rolling release can keep its
    # immediately preceding API replicas interoperable.
    "SESSION_STORAGE_MODE",
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
    "AI_SYSTEM_REQUESTS_PER_MINUTE",
    "AI_SYSTEM_REQUESTS_PER_DAY",
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
    "AI_BACKGROUND_TICKETS_PER_SWEEP",
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
    "FRESHSERVICE_MIN_INTERVAL_SECONDS",
    "FRESHSERVICE_RATE_LIMIT_RESERVE",
    "FRESHSERVICE_RECENT_PAGES_PER_SYNC",
    "FRESHSERVICE_HISTORY_PAGES_PER_SYNC",
    "FRESHSERVICE_CONVERSATIONS_PER_SYNC",
    "FRESHSERVICE_ATTACHMENTS_PER_SYNC",
    "ATTACHMENT_BLOB_DELETIONS_PER_SYNC",
    "ATTACHMENT_BLOB_CLEANUP_INTERVAL_SECONDS",
    "ATTACHMENT_STORAGE_PROVIDER",
    "ATTACHMENT_MAX_BYTES",
    "AZURE_STORAGE_ACCOUNT_URL",
    "AZURE_STORAGE_CONTAINER",
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
    "DIRECTORY_PEOPLE_READ_ENABLED",
    "DIRECTORY_PEOPLE_WRITE_ENABLED",
    "REMOTE_AGENT_TEAM_ELIGIBLE",
    "REMOTE_REQUESTER_TEAM_ELIGIBLE",
    "AUTO_EXACT_EMAIL_LINK_ENABLED",
    "DIRECTORY_SYNC_ENABLED",
    "DIRECTORY_SYNC_INTERVAL_SECONDS",
    "DIRECTORY_SYNC_LEASE_SECONDS",
    "DIRECTORY_STALE_AFTER_SECONDS",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    "FRONTEND_URL",
    # Outbound email
    "SENDGRID_API_KEY",
    "SENDGRID_FROM_EMAIL",
    "SENDGRID_FROM_NAME",
    "SENDGRID_REPLY_TO_EMAIL",
    "EMAIL_SENDS_PER_MINUTE",
    "EMAIL_RECIPIENTS_PER_DAY",
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
    "SSO_ENTRA_TENANT_ID",
    "SSO_OKTA_DOMAIN",
    "SSO_OKTA_AUTH_SERVER_ID",
    "SSO_CLIENT_ID",
    "SSO_CLIENT_SECRET",
    "SSO_DISCOVERY_URL",
    "SSO_REDIRECT_URI",
    "SSO_ALLOWED_DOMAINS",
    "SSO_ALLOWED_GROUP_IDS",
    "SSO_AUTO_PROVISION",
]

# Keys that are static infra config
_READONLY_KEYS = {
    "APP_MODE",
    "TICKETY_ADMIN_SETTINGS_PORTAL_ENABLED",
    "DATABASE_URL",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    # This is selected by the deployment during a rolling release.  An
    # application-level admin must not be able to reopen raw session writes.
    "SESSION_STORAGE_MODE",
    "LLM_ALLOW_PRIVATE_ENDPOINTS",
    "LLM_ALLOW_INSECURE_ENDPOINTS",
    "LLM_ALLOWED_PROVIDER_HOSTS",
    "WEBHOOK_MAX_AGE_SECONDS",
    "TICKET_RAG_SCOPE_KEY",
    "TICKET_RAG_V2_SCOPE_ALLOWLIST",
    "DIRECTORY_PEOPLE_READ_ENABLED",
    "DIRECTORY_PEOPLE_WRITE_ENABLED",
    "REMOTE_AGENT_TEAM_ELIGIBLE",
    "REMOTE_REQUESTER_TEAM_ELIGIBLE",
    "AUTO_EXACT_EMAIL_LINK_ENABLED",
    "DIRECTORY_SYNC_ENABLED",
    "DIRECTORY_SYNC_INTERVAL_SECONDS",
    "DIRECTORY_SYNC_LEASE_SECONDS",
    "DIRECTORY_STALE_AFTER_SECONDS",
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
    "SESSION_STORAGE_MODE",
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
    "AI_SYSTEM_REQUESTS_PER_MINUTE",
    "AI_SYSTEM_REQUESTS_PER_DAY",
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
    "AI_BACKGROUND_TICKETS_PER_SWEEP",
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
    "FRESHSERVICE_MIN_INTERVAL_SECONDS",
    "FRESHSERVICE_RATE_LIMIT_RESERVE",
    "FRESHSERVICE_RECENT_PAGES_PER_SYNC",
    "FRESHSERVICE_HISTORY_PAGES_PER_SYNC",
    "FRESHSERVICE_CONVERSATIONS_PER_SYNC",
    "FRESHSERVICE_ATTACHMENTS_PER_SYNC",
    "ATTACHMENT_BLOB_DELETIONS_PER_SYNC",
    "ATTACHMENT_BLOB_CLEANUP_INTERVAL_SECONDS",
    "ATTACHMENT_STORAGE_PROVIDER",
    "ATTACHMENT_MAX_BYTES",
    "AZURE_STORAGE_ACCOUNT_URL",
    "AZURE_STORAGE_CONTAINER",
    "FRESHSERVICE_OAUTH_CLIENT_ID",
    "FRESHSERVICE_OAUTH_REDIRECT_URI",
    "FRESHSERVICE_OAUTH_SCOPES",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_PROJECT_KEY",
    "JIRA_ISSUE_TYPE",
    "SYNC_INTERVAL_SECONDS",
    "DIRECTORY_PEOPLE_READ_ENABLED",
    "DIRECTORY_PEOPLE_WRITE_ENABLED",
    "REMOTE_AGENT_TEAM_ELIGIBLE",
    "REMOTE_REQUESTER_TEAM_ELIGIBLE",
    "AUTO_EXACT_EMAIL_LINK_ENABLED",
    "DIRECTORY_SYNC_ENABLED",
    "DIRECTORY_SYNC_INTERVAL_SECONDS",
    "DIRECTORY_SYNC_LEASE_SECONDS",
    "DIRECTORY_STALE_AFTER_SECONDS",
    "SENDGRID_FROM_EMAIL",
    "SENDGRID_FROM_NAME",
    "SENDGRID_REPLY_TO_EMAIL",
    "EMAIL_SENDS_PER_MINUTE",
    "EMAIL_RECIPIENTS_PER_DAY",
    "SSO_ENABLED",
    "SSO_PROVIDER",
    "SSO_ENTRA_TENANT_ID",
    "SSO_OKTA_DOMAIN",
    "SSO_OKTA_AUTH_SERVER_ID",
    "SSO_CLIENT_ID",
    "SSO_CLIENT_SECRET",
    "SSO_DISCOVERY_URL",
    "SSO_REDIRECT_URI",
    "SSO_ALLOWED_DOMAINS",
    "SSO_ALLOWED_GROUP_IDS",
    "SSO_AUTO_PROVISION",
}

# Production values saved through the authenticated admin endpoint override
# deployment defaults. Truly static process/bootstrap settings remain in
# _READONLY_KEYS and cannot be changed through the application.
_PRODUCTION_ADMIN_PORTAL_KEYS = _PRODUCTION_ENV_ONLY_KEYS - _READONLY_KEYS
_PRODUCTION_SSO_PORTAL_KEYS = {
    "SSO_ENABLED",
    "SSO_PROVIDER",
    "SSO_ENTRA_TENANT_ID",
    "SSO_OKTA_DOMAIN",
    "SSO_OKTA_AUTH_SERVER_ID",
    "SSO_CLIENT_ID",
    "SSO_CLIENT_SECRET",
    "SSO_DISCOVERY_URL",
    "SSO_ALLOWED_DOMAINS",
    "SSO_ALLOWED_GROUP_IDS",
    "SSO_AUTO_PROVISION",
}
_CLEARABLE_PORTAL_KEYS = _PRODUCTION_SSO_PORTAL_KEYS | {
    "SENDGRID_REPLY_TO_EMAIL",
}
_ADMIN_PORTAL_APPROVAL_PREFIX = "__ADMIN_PORTAL_APPROVED__:"
_SETTINGS_ENCRYPTION_PREFIX = "enc:v1:"
_SETTINGS_ENCRYPTION_AAD_PREFIX = b"tickety.settings.v1\x00"
_SETTINGS_ENCRYPTION_KID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# A durable, non-secret singleton used to serialize sensitive-settings writes
# during a KID rotation.  It deliberately stays outside _ALL_KEYS, so it can
# never become an application override or an administrator-visible setting.
_SETTINGS_ENCRYPTION_FENCE_KEY = "__tickety_settings_encryption_active_kid__"


class SettingsEncryptionError(RuntimeError):
    """A persisted secret cannot be safely read or written."""


class LegacySensitiveSettingError(SettingsEncryptionError):
    """A legacy plaintext database secret requires an explicit migration."""

_lock = threading.Lock()
_loaded = False


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_llm_base_url(value: str) -> str:
    """Validate provider URL policy without depending on live DNS.

    Settings persistence and process initialization use this path. Every
    outbound provider path must still call ``_validate_llm_base_url`` so DNS
    results are checked for private or reserved destinations immediately
    before network I/O.
    """
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

    # IP literals do not require DNS, so reject non-public literals even on
    # configuration-only paths. Hostnames are resolved at the outbound-I/O
    # boundary below.
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise ValueError("LLM base URL must not target a private or reserved address")
    return value.rstrip("/")


def _validate_public_llm_resolution(value: str) -> str:
    if _truthy(os.getenv("LLM_ALLOW_PRIVATE_ENDPOINTS")):
        return value
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        addresses = {str(literal_address)}
    else:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(hostname, parsed.port or 443)
            }
        except socket.gaierror as exc:
            raise ValueError("LLM base URL hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("LLM base URL must not target a private or reserved address")
    return value


def _validate_llm_base_url(value: str) -> str:
    normalized = _normalize_llm_base_url(value)
    return _validate_public_llm_resolution(normalized)


def _normalize_foundry_base_url(value: str) -> str:
    """Validate Microsoft Foundry URL policy without resolving the hostname."""
    normalized = _normalize_llm_base_url(value)
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname.endswith((".services.ai.azure.com", ".openai.azure.com")):
        raise ValueError("Foundry endpoint must use a Microsoft Azure hostname")
    if parsed.path.rstrip("/") != "/openai/v1":
        raise ValueError("Foundry endpoint path must end with /openai/v1")
    return normalized


def _validate_foundry_base_url(value: str) -> str:
    """Validate Foundry policy and public DNS immediately before network I/O."""
    normalized = _normalize_foundry_base_url(value)
    return _validate_public_llm_resolution(normalized)


def get_bool(key: str, default: bool = False, aliases: tuple[str, ...] = ()) -> bool:
    """Read an env-style boolean with optional legacy aliases."""
    for candidate in (key, *aliases):
        value = os.getenv(candidate)
        if value is not None and value != "":
            return _truthy(value)
    return default


def get_int(
    key: str,
    *,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    """Read a bounded integer setting after worker/admin overrides load."""
    try:
        value = int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


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


def session_storage_mode() -> str:
    """Return the browser-session representation selected by deployment.

    ``hashed`` is the secure standalone default.  ``compat`` is deliberately
    opt-in for a mixed old/new API rollout: it retains the legacy raw session
    representation until every legacy replica has been retired.
    """
    mode = (os.getenv("SESSION_STORAGE_MODE") or "hashed").strip().lower()
    if mode not in {"hashed", "compat"}:
        raise ValueError("SESSION_STORAGE_MODE must be either 'hashed' or 'compat'")
    return mode


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


def _settings_encryption_keyring() -> tuple[str, dict[str, bytes]]:
    """Load the deployment-owned AES-256-GCM keyring without defaults.

    The keyring is deliberately an environment-only bootstrap boundary. It is
    never persisted in ``SettingsRecord`` or synthesized by the application.
    """
    active_kid = (os.getenv("TICKETY_SETTINGS_ENCRYPTION_ACTIVE_KID") or "").strip()
    serialized = (os.getenv("TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON") or "").strip()
    if not active_kid or not _SETTINGS_ENCRYPTION_KID_RE.fullmatch(active_kid):
        raise SettingsEncryptionError("settings encryption active KID is missing or invalid")
    try:
        raw_keyring = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise SettingsEncryptionError("settings encryption keyring is missing or invalid") from exc
    if not isinstance(raw_keyring, dict) or not raw_keyring:
        raise SettingsEncryptionError("settings encryption keyring is missing or invalid")

    keyring: dict[str, bytes] = {}
    for kid, encoded_key in raw_keyring.items():
        if not isinstance(kid, str) or not _SETTINGS_ENCRYPTION_KID_RE.fullmatch(kid):
            raise SettingsEncryptionError("settings encryption keyring contains an invalid KID")
        if not isinstance(encoded_key, str):
            raise SettingsEncryptionError("settings encryption keyring contains an invalid key")
        try:
            key = base64.b64decode(encoded_key.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise SettingsEncryptionError("settings encryption keyring contains an invalid key") from exc
        if len(key) != 32:
            raise SettingsEncryptionError("settings encryption keys must be exactly 32 bytes")
        keyring[kid] = key
    if active_kid not in keyring:
        raise SettingsEncryptionError("settings encryption active KID is not in the keyring")
    return active_kid, keyring


def _lock_settings_encryption_fence(
    db, active_kid: str, *, initial_kid: Optional[str] = None
) -> str:
    """Acquire the cross-process sensitive-settings write fence.

    The sentinel ``UPDATE`` is intentional.  PostgreSQL retains a row lock
    for the surrounding transaction; SQLite does not implement ``FOR UPDATE``
    but its write transaction serializes competing settings writers.  Every
    path that persists a sensitive setting must take this fence before it reads
    or modifies a sensitive row.
    """
    seed_kid = initial_kid if initial_kid is not None else active_kid
    if not _SETTINGS_ENCRYPTION_KID_RE.fullmatch(seed_kid):
        raise SettingsEncryptionError("settings encryption durable fence is invalid")
    db.execute(
        text(
            "INSERT INTO settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": _SETTINGS_ENCRYPTION_FENCE_KEY, "value": seed_kid},
    )
    db.execute(
        text("UPDATE settings SET value = value WHERE key = :key"),
        {"key": _SETTINGS_ENCRYPTION_FENCE_KEY},
    )
    fence = (
        db.query(SettingsRecord)
        .filter(SettingsRecord.key == _SETTINGS_ENCRYPTION_FENCE_KEY)
        .with_for_update()
        .one()
    )
    durable_kid = fence.value
    if (
        not isinstance(durable_kid, str)
        or not _SETTINGS_ENCRYPTION_KID_RE.fullmatch(durable_kid)
    ):
        raise SettingsEncryptionError("settings encryption durable fence is invalid")
    return durable_kid


def _verify_settings_encryption_fence(db, active_kid: str) -> None:
    """Fail a read-only release preflight on a mismatched durable KID."""
    fence = db.get(SettingsRecord, _SETTINGS_ENCRYPTION_FENCE_KEY)
    if fence is None:
        # A first fence-aware deployment must still be able to start with its
        # established old active KID.  It may not use a missing marker to
        # smuggle in a new active KID over existing old envelopes, however.
        rows = db.query(SettingsRecord).filter(
            SettingsRecord.key.in_(_SENSITIVE_KEYS)
        ).all()
        for row in rows:
            value = row.value
            if isinstance(value, str) and value.startswith(_SETTINGS_ENCRYPTION_PREFIX):
                envelope_kid = value[len(_SETTINGS_ENCRYPTION_PREFIX):].partition(":")[0]
                if envelope_kid != active_kid:
                    raise SettingsEncryptionError(
                        "settings encryption unfenced ciphertext does not match active KID"
                    )
        return
    durable_kid = fence.value
    if (
        not isinstance(durable_kid, str)
        or not _SETTINGS_ENCRYPTION_KID_RE.fullmatch(durable_kid)
        or durable_kid != active_kid
    ):
        raise SettingsEncryptionError(
            "settings encryption active KID does not match durable fence"
        )
    # The fence is a deployment-wide cipher generation, not merely a marker
    # for future writes.  Accepting a database with mixed envelope KIDs would
    # let startup and release preflight run while a retired writer's secret
    # remained live.  Require every persisted sensitive value to belong to
    # the same durable generation before a process can hydrate it.
    _require_sensitive_rows_match_active_kid(db, active_kid)


def _require_sensitive_rows_match_active_kid(db, active_kid: str) -> None:
    """Do not let a normal write claim a new fence over old ciphertext."""
    rows = db.query(SettingsRecord).filter(
        SettingsRecord.key.in_(_SENSITIVE_KEYS)
    ).all()
    for row in rows:
        value = row.value
        if value is None:
            continue
        if not isinstance(value, str) or not value.startswith(_SETTINGS_ENCRYPTION_PREFIX):
            raise LegacySensitiveSettingError(
                "legacy plaintext sensitive settings require explicit migration"
            )
        envelope_kid = value[len(_SETTINGS_ENCRYPTION_PREFIX):].partition(":")[0]
        if envelope_kid != active_kid:
            raise SettingsEncryptionError(
                "persisted sensitive settings do not match the durable active KID"
            )


def _settings_encryption_aad(key: str) -> bytes:
    return _SETTINGS_ENCRYPTION_AAD_PREFIX + key.encode("utf-8")


def _encrypt_sensitive_setting(key: str, value: str) -> str:
    active_kid, keyring = _settings_encryption_keyring()
    # AESGCM.encrypt returns nonce-free bytes; retain a fresh nonce beside the
    # ciphertext in a versioned, self-describing envelope.
    nonce = os.urandom(12)
    ciphertext = AESGCM(keyring[active_kid]).encrypt(
        nonce, value.encode("utf-8"), _settings_encryption_aad(key)
    )
    encoded = base64.b64encode(nonce + ciphertext).decode("ascii")
    return f"{_SETTINGS_ENCRYPTION_PREFIX}{active_kid}:{encoded}"


def _decrypt_sensitive_setting(key: str, stored_value: Optional[str]) -> Optional[str]:
    if stored_value is None:
        return None
    if not isinstance(stored_value, str) or not stored_value.startswith(_SETTINGS_ENCRYPTION_PREFIX):
        raise LegacySensitiveSettingError(
            f"persisted plaintext sensitive setting requires explicit migration: {key}"
        )
    remainder = stored_value[len(_SETTINGS_ENCRYPTION_PREFIX):]
    kid, separator, encoded = remainder.partition(":")
    if not separator or not _SETTINGS_ENCRYPTION_KID_RE.fullmatch(kid) or not encoded:
        raise SettingsEncryptionError(f"persisted sensitive setting envelope is invalid: {key}")
    _active_kid, keyring = _settings_encryption_keyring()
    secret_key = keyring.get(kid)
    if secret_key is None:
        raise SettingsEncryptionError(f"persisted sensitive setting uses an unknown KID: {key}")
    try:
        payload = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise SettingsEncryptionError(f"persisted sensitive setting ciphertext is invalid: {key}") from exc
    if len(payload) < 12 + 16:
        raise SettingsEncryptionError(f"persisted sensitive setting ciphertext is invalid: {key}")
    try:
        return AESGCM(secret_key).decrypt(
            payload[:12], payload[12:], _settings_encryption_aad(key)
        ).decode("utf-8")
    except (InvalidTag, UnicodeDecodeError) as exc:
        raise SettingsEncryptionError(f"persisted sensitive setting cannot be authenticated: {key}") from exc


def _encode_db_override(key: str, value: Optional[str]) -> Optional[str]:
    if key in _SENSITIVE_KEYS and value is not None:
        return _encrypt_sensitive_setting(key, value)
    return value


def _decode_db_override(key: str, value: Optional[str]) -> Optional[str]:
    if key in _SENSITIVE_KEYS:
        return _decrypt_sensitive_setting(key, value)
    return value


def _read_db_overrides() -> dict:
    """Return settings overrides stored in DB (key -> value)."""
    db = SessionLocal()
    try:
        # SettingsRecord also carries bounded internal state. Never turn an
        # arbitrary or legacy row into a process environment variable.
        rows = db.query(SettingsRecord).filter(SettingsRecord.key.in_(_ALL_KEYS)).all()
    except Exception:
        return {}
    finally:
        db.close()
    # Keep database availability compatibility, but never convert a keyring,
    # envelope, authentication, or legacy-plaintext failure into an empty
    # settings set. Doing so could silently run with an unintended secret.
    return {r.key: _decode_db_override(r.key, r.value) for r in rows}


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
        if any(key in _SENSITIVE_KEYS for key in updates):
            active_kid, _keyring = _settings_encryption_keyring()
            durable_kid = _lock_settings_encryption_fence(db, active_kid)
            if durable_kid != active_kid:
                raise SettingsEncryptionError(
                    "settings encryption active KID does not match durable fence"
                )
            _require_sensitive_rows_match_active_kid(db, active_kid)
        for key, value in updates.items():
            existing = db.query(SettingsRecord).filter(SettingsRecord.key == key).first()
            persisted_value = _encode_db_override(key, value)
            if existing:
                existing.value = persisted_value
            else:
                db.add(SettingsRecord(key=key, value=persisted_value))
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


def persist_runtime_secret_updates(updates: dict[str, str]) -> None:
    """Persist runtime-issued integration secrets through the shared cipher.

    This intentionally accepts only recognized sensitive settings so provider
    refresh code cannot bypass the at-rest encryption boundary.
    """
    if not updates or any(key not in _SENSITIVE_KEYS for key in updates):
        raise ValueError("runtime secret persistence accepts sensitive settings only")
    _write_db_overrides(updates)
    for key, value in updates.items():
        os.environ[key] = value


def persist_runtime_oauth_tokens_if_current(
    *,
    expected_access_token: str,
    expected_refresh_token: str,
    access_token: str,
    refresh_token: str,
) -> bool:
    """Atomically publish a refreshed OAuth pair only from its live parent.

    A refresh token can rotate at the provider.  API and worker replicas retain
    independent adapter instances, so an old instance must never overwrite a
    newer pair merely because its remote request completed later.  The durable
    durable access-and-refresh pair is the compare-and-swap version; values
    are decrypted only inside this settings boundary and are neither logged
    nor returned.  Both values matter because providers may reuse a refresh
    token while issuing a new access token.

    A missing durable pair may be bootstrapped once from a configured runtime
    refresh token, including a recovery refresh where the local access token
    has already been lost.  Once either row exists, incomplete pairs fail
    closed, and a durable pair always requires both parent values to match.
    """
    if (
        not isinstance(expected_access_token, str)
        or not all(isinstance(value, str) and value for value in (
            expected_refresh_token, access_token, refresh_token,
        ))
    ):
        raise ValueError("runtime OAuth token persistence requires string tokens")

    access_key = "FRESHSERVICE_OAUTH_ACCESS_TOKEN"
    refresh_key = "FRESHSERVICE_OAUTH_REFRESH_TOKEN"
    db = SessionLocal()
    try:
        active_kid, _keyring = _settings_encryption_keyring()
        durable_kid = _lock_settings_encryption_fence(db, active_kid)
        if durable_kid != active_kid:
            raise SettingsEncryptionError(
                "settings encryption active KID does not match durable fence"
            )
        _require_sensitive_rows_match_active_kid(db, active_kid)
        rows = {
            row.key: row
            for row in db.query(SettingsRecord).filter(
                SettingsRecord.key.in_((access_key, refresh_key))
            ).with_for_update().all()
        }
        persisted_access = rows.get(access_key)
        persisted_refresh = rows.get(refresh_key)
        if persisted_access is not None or persisted_refresh is not None:
            if persisted_access is None or persisted_refresh is None:
                db.rollback()
                return False
            # An empty local access token has no durable pair version to
            # compare.  It may bootstrap a wholly absent pair below, but must
            # never replace an existing pair based only on a refresh token.
            if not expected_access_token:
                db.rollback()
                return False
            durable_access = _decode_db_override(access_key, persisted_access.value)
            durable_refresh = _decode_db_override(refresh_key, persisted_refresh.value)
            if (
                not isinstance(durable_access, str)
                or not isinstance(durable_refresh, str)
                or not hmac.compare_digest(durable_access, expected_access_token)
                or not hmac.compare_digest(durable_refresh, expected_refresh_token)
            ):
                db.rollback()
                return False

        encoded_access = _encode_db_override(access_key, access_token)
        encoded_refresh = _encode_db_override(refresh_key, refresh_token)
        if persisted_access is None:
            db.add(SettingsRecord(key=access_key, value=encoded_access))
        else:
            persisted_access.value = encoded_access
        if persisted_refresh is None:
            db.add(SettingsRecord(key=refresh_key, value=encoded_refresh))
        else:
            persisted_refresh.value = encoded_refresh
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reencrypt_persisted_sensitive_settings(
    *,
    allow_legacy_plaintext: bool = False,
    from_kid: Optional[str] = None,
) -> dict[str, int]:
    """Re-encrypt sensitive rows under the active KID in one transaction.

    Legacy plaintext requires an explicit operator opt-in. This makes a
    plaintext-to-envelope migration visible and prevents accidental adoption
    of an unreviewed old database.
    """
    active_kid, _keyring = _settings_encryption_keyring()
    if from_kid is not None and (
        not isinstance(from_kid, str)
        or not _SETTINGS_ENCRYPTION_KID_RE.fullmatch(from_kid)
    ):
        raise SettingsEncryptionError("settings encryption previous KID is invalid")
    db = SessionLocal()
    migrated = 0
    reencrypted = 0
    try:
        # A pre-fence database can only be adopted through an explicit KID
        # assertion when it already contains secret envelopes.  Otherwise an
        # operator could switch local active=new and silently claim old rows.
        fence_existed = db.get(SettingsRecord, _SETTINGS_ENCRYPTION_FENCE_KEY) is not None
        durable_kid = _lock_settings_encryption_fence(
            db, active_kid, initial_kid=from_kid or active_kid
        )
        rows = (
            db.query(SettingsRecord)
            .filter(SettingsRecord.key.in_(_SENSITIVE_KEYS))
            .with_for_update()
            .all()
        )
        if not fence_existed and rows and from_kid is None:
            raise SettingsEncryptionError(
                "settings encryption bootstrap requires --from-kid for existing sensitive settings"
            )
        if durable_kid != active_kid:
            if from_kid != durable_kid:
                raise SettingsEncryptionError(
                    "settings encryption rotation requires --from-kid matching the durable fence"
                )
            db.execute(
                text("UPDATE settings SET value = :value WHERE key = :key"),
                {"key": _SETTINGS_ENCRYPTION_FENCE_KEY, "value": active_kid},
            )
        elif from_kid is not None and from_kid != durable_kid:
            raise SettingsEncryptionError(
                "settings encryption --from-kid does not match the durable fence"
            )

        for row in rows:
            value = row.value
            if value is None:
                continue
            if value.startswith(_SETTINGS_ENCRYPTION_PREFIX):
                plaintext = _decrypt_sensitive_setting(row.key, value)
                envelope_kid = value[len(_SETTINGS_ENCRYPTION_PREFIX):].partition(":")[0]
                if envelope_kid == active_kid:
                    continue
                reencrypted += 1
            else:
                if not allow_legacy_plaintext:
                    raise LegacySensitiveSettingError(
                        "legacy plaintext sensitive settings found; rerun with explicit migration approval"
                    )
                plaintext = value
                migrated += 1
            row.value = _encrypt_sensitive_setting(row.key, plaintext)
        db.commit()
        return {"migrated_plaintext": migrated, "reencrypted": reencrypted}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _validate_runtime_settings_encryption_fence() -> None:
    """Reject an active-KID cutover bypass before runtime hydration.

    Keep the historical startup fallback for a missing/unavailable settings
    table: that state has no durable settings to decrypt.  Once the database
    contains either a fence or any sensitive row, a process must prove its
    local keyring agrees with the durable boundary before it can hydrate and
    serve with those values.
    """
    db = SessionLocal()
    try:
        fence = db.get(SettingsRecord, _SETTINGS_ENCRYPTION_FENCE_KEY)
        has_sensitive_rows = (
            db.query(SettingsRecord.key)
            .filter(SettingsRecord.key.in_(_SENSITIVE_KEYS))
            .first()
            is not None
        )
    except Exception:
        return
    finally:
        db.close()
    if fence is None and not has_sensitive_rows:
        return
    active_kid, _keyring = _settings_encryption_keyring()
    # Re-open because the first session is deliberately closed before the
    # keyring parse; no lock is required for this read-only startup check.
    db = SessionLocal()
    try:
        _verify_settings_encryption_fence(db, active_kid)
    finally:
        db.close()


def load_settings_into_env() -> bool:
    """At startup, hydrate os.environ with DB-stored overrides so every
    module that reads env once at import time still sees the saved values."""
    global _loaded
    with _lock:
        _validate_runtime_settings_encryption_fence()
        overrides = _read_db_overrides()
        production = is_production_mode()
        # Only overrides carrying an approval marker written by an
        # authenticated administrator may supersede production defaults.
        approved_keys = _read_portal_approved_keys() if production else set()
        changed = False
        for key, value in overrides.items():
            if key not in _ALL_KEYS or key in _READONLY_KEYS:
                continue
            if production and key in _PRODUCTION_ENV_ONLY_KEYS:
                if key not in approved_keys:
                    continue
            if value is not None:
                if key in _LLM_BASE_URL_KEYS and value:
                    value = (
                        _normalize_foundry_base_url(value)
                        if key == "FOUNDRY_API_BASE"
                        else _normalize_llm_base_url(value)
                    )
                changed = changed or os.getenv(key) != value
                os.environ[key] = value
        validate_effective_llm_urls()
        _loaded = True
        return changed


def validate_effective_llm_urls() -> None:
    """Validate stored URL policy without coupling app readiness to DNS."""
    for key in _LLM_BASE_URL_KEYS:
        value = (os.getenv(key) or "").strip()
        if value:
            os.environ[key] = (
                _normalize_foundry_base_url(value)
                if key == "FOUNDRY_API_BASE"
                else _normalize_llm_base_url(value)
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
        proposed_provider = str(payload.get("SSO_PROVIDER") or os.getenv("SSO_PROVIDER") or "").strip()
        proposed_client_id = str(payload.get("SSO_CLIENT_ID") or os.getenv("SSO_CLIENT_ID") or "").strip()
        provider_changed = "SSO_PROVIDER" in payload and proposed_provider != str(os.getenv("SSO_PROVIDER") or "").strip()
        client_changed = "SSO_CLIENT_ID" in payload and proposed_client_id != str(os.getenv("SSO_CLIENT_ID") or "").strip()
        if (provider_changed or client_changed) and os.getenv("SSO_CLIENT_SECRET"):
            replacement = payload.get("SSO_CLIENT_SECRET")
            if not (
                isinstance(replacement, str)
                and replacement.strip()
                and "****" not in replacement
            ):
                raise ValueError(
                    "Changing the SSO provider or client ID requires re-entering SSO_CLIENT_SECRET"
                )
        updates = {}
        for key in _ALL_KEYS:
            if key not in payload or key in _READONLY_KEYS:
                continue
            if production and key in _PRODUCTION_ENV_ONLY_KEYS:
                if not actor_id:
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
                if key not in _CLEARABLE_PORTAL_KEYS:
                    new_val = os.getenv(key, "")
            if key in _LLM_BASE_URL_KEYS and new_val:
                new_val = (
                    _normalize_foundry_base_url(new_val)
                    if key == "FOUNDRY_API_BASE"
                    else _normalize_llm_base_url(new_val)
                )
            if key in {"DEFAULT_MODEL", "TICKET_EMBEDDING_MODEL"}:
                from .llm_manager import resolve_provider

                resolve_provider(new_val)
            if key == "FOUNDRY_AUTH_METHOD" and new_val not in {"api_key", "entra"}:
                raise ValueError("FOUNDRY_AUTH_METHOD must be 'api_key' or 'entra'")
            if key == "SSO_PROVIDER" and new_val not in {"entra", "okta", "oidc"}:
                raise ValueError("SSO_PROVIDER must be 'entra', 'okta', or 'oidc'")
            if key == "SSO_ENTRA_TENANT_ID" and new_val:
                try:
                    new_val = str(uuid.UUID(new_val))
                except ValueError as exc:
                    raise ValueError("SSO_ENTRA_TENANT_ID must be a tenant ID GUID") from exc
            if key == "SSO_ALLOWED_GROUP_IDS" and new_val:
                provider = str(payload.get("SSO_PROVIDER") or os.getenv("SSO_PROVIDER") or "entra")
                if provider == "entra":
                    try:
                        new_val = ",".join(
                            str(uuid.UUID(value.strip()))
                            for value in new_val.split(",")
                            if value.strip()
                        )
                    except ValueError as exc:
                        raise ValueError(
                            "SSO_ALLOWED_GROUP_IDS must contain Entra group object ID GUIDs"
                        ) from exc
            if key == "FRESHSERVICE_OAUTH_SCOPES" and new_val:
                from .integrations.freshservice import FreshserviceAdapter

                new_val = FreshserviceAdapter._validate_oauth_scopes(new_val)
            if key in {"SENDGRID_FROM_EMAIL", "SENDGRID_REPLY_TO_EMAIL"} and new_val:
                try:
                    new_val = normalize_email_address(new_val)
                except ValueError as exc:
                    raise ValueError(f"{key} must be a valid email address") from exc
            if key == "SENDGRID_FROM_NAME" and new_val:
                try:
                    new_val = normalize_sender_name(new_val)
                except ValueError as exc:
                    raise ValueError("SENDGRID_FROM_NAME is invalid") from exc
                if not new_val:
                    raise ValueError("SENDGRID_FROM_NAME cannot be blank")
            if key == "ATTACHMENT_STORAGE_PROVIDER" and new_val not in {
                "", "azure_blob",
            }:
                raise ValueError(
                    "ATTACHMENT_STORAGE_PROVIDER must be 'azure_blob' or blank"
                )
            if key == "AZURE_STORAGE_ACCOUNT_URL" and new_val:
                parsed = urlparse(new_val)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                    or parsed.path not in {"", "/"}
                ):
                    raise ValueError(
                        "AZURE_STORAGE_ACCOUNT_URL must be an Azure Blob HTTPS endpoint URL"
                    )
                new_val = new_val.rstrip("/")
            if key == "AZURE_STORAGE_CONTAINER" and new_val:
                if not re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?", new_val
                ):
                    raise ValueError("AZURE_STORAGE_CONTAINER is not a valid container name")
            freshservice_numeric_bounds = {
                "FRESHSERVICE_MIN_INTERVAL_SECONDS": (0.25, 60.0, float),
                "FRESHSERVICE_RATE_LIMIT_RESERVE": (2, 10_000, int),
                "FRESHSERVICE_RECENT_PAGES_PER_SYNC": (1, 10, int),
                "FRESHSERVICE_HISTORY_PAGES_PER_SYNC": (1, 5, int),
                "FRESHSERVICE_CONVERSATIONS_PER_SYNC": (0, 5, int),
                "FRESHSERVICE_ATTACHMENTS_PER_SYNC": (0, 20, int),
                "ATTACHMENT_BLOB_DELETIONS_PER_SYNC": (0, 20, int),
                "ATTACHMENT_BLOB_CLEANUP_INTERVAL_SECONDS": (30, 86_400, int),
                "ATTACHMENT_MAX_BYTES": (1_048_576, 104_857_600, int),
            }
            if key in freshservice_numeric_bounds and new_val:
                minimum, maximum, parser = freshservice_numeric_bounds[key]
                try:
                    parsed = parser(new_val)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{key} must be numeric") from exc
                if parsed < minimum or parsed > maximum:
                    raise ValueError(
                        f"{key} must be between {minimum} and {maximum}"
                    )
                new_val = str(parsed)
            email_numeric_bounds = {
                "EMAIL_SENDS_PER_MINUTE": (1, 60),
                "EMAIL_RECIPIENTS_PER_DAY": (1, 10_000),
            }
            if key in email_numeric_bounds and new_val:
                minimum, maximum = email_numeric_bounds[key]
                try:
                    parsed = int(new_val)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{key} must be an integer") from exc
                if parsed < minimum or parsed > maximum:
                    raise ValueError(
                        f"{key} must be between {minimum} and {maximum}"
                    )
                new_val = str(parsed)
            updates[key] = new_val

        if updates:
            approved_keys = {
                key
                for key in updates
                if production and (
                    key in _PRODUCTION_ADMIN_PORTAL_KEYS
                    or key in _PRODUCTION_SSO_PORTAL_KEYS
                )
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
            # Settings reload is not an authorization to block an API process
            # indefinitely behind an already-running scheduled job. Durable
            # checkpoints make the next scheduler sweep safe to resume.
            sync_worker.stop_sync_worker(wait=False)
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
