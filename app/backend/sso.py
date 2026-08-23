"""OpenID Connect configuration and protocol helpers.

The deployment surface intentionally keeps provider-specific input small:

* Microsoft Entra ID: tenant ID, client ID, and client secret.
* Okta: organization domain, client ID, and client secret.

Discovery and callback URLs are derived from those values.  The legacy generic
OIDC settings remain supported for installations that use another provider.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import socket
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from . import settings as settings_module


SSO_CALLBACK_PATH = "/api/auth/sso/callback"
SSO_TRANSACTION_TTL_SECONDS = 600
_MAX_OIDC_DOCUMENT_BYTES = 256 * 1024
_SAFE_ID_TOKEN_ALGORITHMS = {
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
}
_ENTRA_ALIASES = {
    "entra",
    "entra id",
    "azure ad",
    "azure active directory",
    "microsoft entra",
    "microsoft entra id",
}
_OKTA_ALIASES = {"okta"}
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+$")


class SsoConfigurationError(ValueError):
    """A deployment-owned SSO setting is absent or unsafe."""


class SsoProtocolError(ValueError):
    """The identity provider returned an invalid OIDC response."""


@dataclass(frozen=True)
class SsoRuntimeConfig:
    provider_type: str
    provider_name: str
    client_id: str
    client_secret: str
    discovery_url: str
    redirect_uri: str
    expected_issuer: str | None


@dataclass(frozen=True)
class OidcIdentity:
    issuer: str
    subject: str
    email: str
    name: str


def _provider_type(raw: str | None = None) -> str:
    normalized = str(raw if raw is not None else os.getenv("SSO_PROVIDER", "")).strip().lower()
    if normalized in _ENTRA_ALIASES:
        return "entra"
    if normalized in _OKTA_ALIASES:
        return "okta"
    return "oidc"


def _provider_name(provider_type: str, raw: str | None = None) -> str:
    if provider_type == "entra":
        return "Microsoft Entra ID"
    if provider_type == "okta":
        return "Okta"
    return str(raw if raw is not None else os.getenv("SSO_PROVIDER", "")).strip() or "Single Sign-On"


def _normalized_frontend_origin() -> str:
    value = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SsoConfigurationError("FRONTEND_URL must be an absolute HTTP(S) URL")
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SsoConfigurationError("FRONTEND_URL must contain only an origin")
    if settings_module.is_production_mode() and parsed.scheme != "https":
        raise SsoConfigurationError("production SSO requires an HTTPS FRONTEND_URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def _validate_redirect_uri(value: str, frontend_origin: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SsoConfigurationError("SSO redirect URI must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SsoConfigurationError("SSO redirect URI must not contain credentials, query, or fragment")
    if parsed.path != SSO_CALLBACK_PATH:
        raise SsoConfigurationError(f"SSO redirect URI path must be {SSO_CALLBACK_PATH}")
    if settings_module.is_production_mode() and parsed.scheme != "https":
        raise SsoConfigurationError("production SSO redirect URI must use HTTPS")
    redirect_origin = f"{parsed.scheme}://{parsed.netloc}"
    if frontend_origin and redirect_origin != frontend_origin:
        raise SsoConfigurationError("SSO redirect URI must use the FRONTEND_URL origin")
    return f"{redirect_origin}{SSO_CALLBACK_PATH}"


def _validate_discovery_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SsoConfigurationError("SSO discovery URL must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SsoConfigurationError("SSO discovery URL must not contain credentials, query, or fragment")
    if not parsed.path.endswith("/.well-known/openid-configuration"):
        raise SsoConfigurationError("SSO discovery URL must end with /.well-known/openid-configuration")
    return value.rstrip("/")


def _entra_issuer() -> str:
    tenant = (os.getenv("SSO_ENTRA_TENANT_ID") or "").strip()
    if not tenant:
        raise SsoConfigurationError("SSO_ENTRA_TENANT_ID is required for Microsoft Entra ID")
    if tenant.lower() in {"common", "organizations", "consumers"}:
        raise SsoConfigurationError("Microsoft Entra ID SSO requires a tenant-specific identifier")
    try:
        tenant = str(uuid.UUID(tenant))
    except ValueError as exc:
        raise SsoConfigurationError(
            "SSO_ENTRA_TENANT_ID must be the Directory (tenant) ID GUID"
        ) from exc
    return f"https://login.microsoftonline.com/{tenant}/v2.0"


def _okta_issuer() -> str:
    configured = (os.getenv("SSO_OKTA_DOMAIN") or "").strip()
    if not configured:
        raise SsoConfigurationError("SSO_OKTA_DOMAIN is required for Okta")
    candidate = configured if "://" in configured else f"https://{configured}"
    parsed = urllib.parse.urlparse(candidate)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SsoConfigurationError("SSO_OKTA_DOMAIN has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SsoConfigurationError("SSO_OKTA_DOMAIN must be an HTTPS Okta organization hostname")
    hostname = parsed.hostname.lower().rstrip(".")
    if not _HOST_LABEL_RE.fullmatch(hostname) or ".." in hostname:
        raise SsoConfigurationError("SSO_OKTA_DOMAIN is invalid")
    server_id = (os.getenv("SSO_OKTA_AUTH_SERVER_ID") or "org").strip()
    if server_id.lower() == "org":
        return f"https://{hostname}"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", server_id):
        raise SsoConfigurationError("SSO_OKTA_AUTH_SERVER_ID is invalid")
    return f"https://{hostname}/oauth2/{server_id}"


def resolve_sso_config() -> SsoRuntimeConfig:
    """Resolve presets while preserving the legacy generic OIDC settings."""
    if not settings_module.get_bool("SSO_ENABLED", default=False):
        raise SsoConfigurationError("SSO is disabled")

    raw_provider = (os.getenv("SSO_PROVIDER") or "").strip()
    provider_type = _provider_type(raw_provider)
    provider_name = _provider_name(provider_type, raw_provider)
    client_id = (os.getenv("SSO_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SSO_CLIENT_SECRET") or "").strip()
    if not client_id:
        raise SsoConfigurationError("SSO_CLIENT_ID is required")
    if not client_secret:
        raise SsoConfigurationError("SSO_CLIENT_SECRET is required")

    expected_issuer: str | None
    legacy_discovery_url = (os.getenv("SSO_DISCOVERY_URL") or "").strip()
    if provider_type == "entra":
        if (os.getenv("SSO_ENTRA_TENANT_ID") or "").strip():
            expected_issuer = _entra_issuer()
            discovery_url = f"{expected_issuer}/.well-known/openid-configuration"
        elif legacy_discovery_url:
            expected_issuer = None
            discovery_url = legacy_discovery_url
        else:
            expected_issuer = _entra_issuer()
    elif provider_type == "okta":
        if (os.getenv("SSO_OKTA_DOMAIN") or "").strip():
            expected_issuer = _okta_issuer()
            discovery_url = f"{expected_issuer}/.well-known/openid-configuration"
        elif legacy_discovery_url:
            expected_issuer = None
            discovery_url = legacy_discovery_url
        else:
            expected_issuer = _okta_issuer()
    else:
        expected_issuer = None
        discovery_url = legacy_discovery_url
        if not discovery_url:
            raise SsoConfigurationError("SSO_DISCOVERY_URL is required for a generic OIDC provider")
    discovery_url = _validate_discovery_url(discovery_url)

    frontend_origin = _normalized_frontend_origin()
    redirect_uri = (os.getenv("SSO_REDIRECT_URI") or "").strip()
    if not redirect_uri:
        if not frontend_origin:
            raise SsoConfigurationError("FRONTEND_URL or SSO_REDIRECT_URI is required")
        redirect_uri = f"{frontend_origin}{SSO_CALLBACK_PATH}"
    redirect_uri = _validate_redirect_uri(redirect_uri, frontend_origin)

    return SsoRuntimeConfig(
        provider_type=provider_type,
        provider_name=provider_name,
        client_id=client_id,
        client_secret=client_secret,
        discovery_url=discovery_url,
        redirect_uri=redirect_uri,
        expected_issuer=expected_issuer,
    )


def public_sso_config() -> dict[str, Any]:
    requested = settings_module.get_bool("SSO_ENABLED", default=False)
    provider_type = _provider_type()
    provider_name = _provider_name(provider_type)
    if not requested:
        return {
            "enabled": False,
            "ready": False,
            "provider": provider_name,
            "provider_type": provider_type,
            "redirect_uri": "",
        }
    try:
        config = resolve_sso_config()
    except SsoConfigurationError:
        return {
            "enabled": True,
            "ready": False,
            "provider": provider_name,
            "provider_type": provider_type,
            "redirect_uri": "",
        }
    return {
        "enabled": True,
        "ready": True,
        "provider": config.provider_name,
        "provider_type": config.provider_type,
        "redirect_uri": config.redirect_uri,
    }


def safe_next_path(value: str | None) -> str:
    candidate = str(value or "").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme or parsed.netloc or "\\" in candidate or any(ord(ch) < 32 for ch in candidate):
        return "/"
    if parsed.path.startswith("/login") or parsed.path.startswith("/api/auth/"):
        return "/"
    return urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_url(
    metadata: dict[str, Any],
    config: SsoRuntimeConfig,
    *,
    state: str,
    nonce: str,
    code_verifier: str,
) -> str:
    endpoint = str(metadata.get("authorization_endpoint") or "")
    if not endpoint:
        raise SsoProtocolError("OIDC provider is missing authorization_endpoint")
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    separator = "&" if urllib.parse.urlsplit(endpoint).query else "?"
    return f"{endpoint}{separator}{urllib.parse.urlencode(params)}"


def _validate_public_hostname(hostname: str, port: int = 443) -> None:
    normalized = hostname.lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith((".localhost", ".local", ".internal")):
        raise SsoProtocolError("OIDC endpoint hostname is not public")
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise SsoProtocolError("OIDC endpoint address is not public")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(normalized, port)}
    except socket.gaierror as exc:
        raise SsoProtocolError("OIDC endpoint hostname could not be resolved") from exc
    if not addresses:
        raise SsoProtocolError("OIDC endpoint hostname could not be resolved")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise SsoProtocolError("OIDC endpoint resolved to a non-public address")


async def _validated_public_https_url(value: str, label: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SsoProtocolError(f"OIDC provider {label} must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise SsoProtocolError(f"OIDC provider {label} is invalid")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SsoProtocolError(f"OIDC provider {label} has an invalid port") from exc
    if port not in {None, 443}:
        raise SsoProtocolError(f"OIDC provider {label} must use port 443")
    await asyncio.to_thread(_validate_public_hostname, parsed.hostname, port or 443)
    return value


async def fetch_oidc_metadata(config: SsoRuntimeConfig) -> dict[str, Any]:
    await _validated_public_https_url(config.discovery_url, "discovery URL")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(
                config.discovery_url,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            if len(response.content) > _MAX_OIDC_DOCUMENT_BYTES:
                raise SsoProtocolError("OIDC discovery document is too large")
            metadata = response.json()
    except SsoProtocolError:
        raise
    except Exception as exc:
        raise SsoProtocolError("OIDC discovery failed") from exc
    if not isinstance(metadata, dict):
        raise SsoProtocolError("OIDC discovery document is invalid")

    issuer = str(metadata.get("issuer") or "").strip()
    if not issuer:
        raise SsoProtocolError("OIDC provider is missing issuer")
    if config.expected_issuer and issuer != config.expected_issuer:
        raise SsoProtocolError("OIDC provider issuer does not match the configured provider")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = str(metadata.get(key) or "")
        if not value:
            raise SsoProtocolError(f"OIDC provider is missing {key}")
        await _validated_public_https_url(value, key)
    userinfo = str(metadata.get("userinfo_endpoint") or "")
    if userinfo:
        await _validated_public_https_url(userinfo, "userinfo_endpoint")
    return metadata


async def exchange_authorization_code(
    metadata: dict[str, Any],
    config: SsoRuntimeConfig,
    *,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    token_endpoint = str(metadata.get("token_endpoint") or "")
    await _validated_public_https_url(token_endpoint, "token_endpoint")
    advertised_methods = metadata.get("token_endpoint_auth_methods_supported")
    methods = {
        str(value)
        for value in advertised_methods
        if isinstance(value, str)
    } if isinstance(advertised_methods, list) else set()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
        "client_id": config.client_id,
        "code_verifier": code_verifier,
    }
    auth: httpx.BasicAuth | None = None
    if "client_secret_post" in methods:
        data["client_secret"] = config.client_secret
    elif "client_secret_basic" in methods or not methods:
        auth = httpx.BasicAuth(config.client_id, config.client_secret)
    else:
        raise SsoProtocolError("OIDC provider does not support client secret authentication")
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post(token_endpoint, data=data, auth=auth)
            response.raise_for_status()
            if len(response.content) > _MAX_OIDC_DOCUMENT_BYTES:
                raise SsoProtocolError("OIDC token response is too large")
            payload = response.json()
    except SsoProtocolError:
        raise
    except Exception as exc:
        raise SsoProtocolError("OIDC authorization code exchange failed") from exc
    if not isinstance(payload, dict) or not payload.get("id_token"):
        raise SsoProtocolError("OIDC token response is missing id_token")
    return payload


async def _fetch_jwks(jwks_uri: str) -> dict[str, Any]:
    await _validated_public_https_url(jwks_uri, "jwks_uri")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(jwks_uri, headers={"Accept": "application/json"})
            response.raise_for_status()
            if len(response.content) > _MAX_OIDC_DOCUMENT_BYTES:
                raise SsoProtocolError("OIDC signing-key document is too large")
            payload = response.json()
    except SsoProtocolError:
        raise
    except Exception as exc:
        raise SsoProtocolError("OIDC signing-key retrieval failed") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise SsoProtocolError("OIDC signing-key document is invalid")
    return payload


async def validate_id_token(
    id_token: str,
    metadata: dict[str, Any],
    config: SsoRuntimeConfig,
    *,
    nonce: str,
) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise SsoProtocolError("OIDC id_token header is invalid") from exc
    algorithm = str(header.get("alg") or "")
    advertised_algorithms = metadata.get("id_token_signing_alg_values_supported")
    advertised = {
        str(value)
        for value in advertised_algorithms
        if isinstance(value, str)
    } if isinstance(advertised_algorithms, list) else set()
    allowed = _SAFE_ID_TOKEN_ALGORITHMS & advertised if advertised else {"RS256"}
    if algorithm not in allowed:
        raise SsoProtocolError("OIDC id_token uses an unsupported signing algorithm")
    kid = str(header.get("kid") or "")
    if not kid:
        raise SsoProtocolError("OIDC id_token is missing a signing-key identifier")
    jwks = await _fetch_jwks(str(metadata.get("jwks_uri") or ""))
    candidates = [key for key in jwks["keys"] if isinstance(key, dict) and key.get("kid") == kid]
    if len(candidates) != 1:
        raise SsoProtocolError("OIDC signing key was not found")
    try:
        signing_key = jwt.PyJWK.from_dict(candidates[0], algorithm=algorithm).key
        claims = jwt.decode(
            id_token,
            key=signing_key,
            algorithms=[algorithm],
            audience=config.client_id,
            issuer=str(metadata.get("issuer") or "").strip(),
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
    except jwt.PyJWTError as exc:
        raise SsoProtocolError("OIDC id_token validation failed") from exc
    audience = claims.get("aud")
    authorized_party = str(claims.get("azp") or "")
    if isinstance(audience, list) and len(audience) > 1:
        if authorized_party != config.client_id:
            raise SsoProtocolError("OIDC id_token authorized party does not match")
    elif authorized_party and authorized_party != config.client_id:
        raise SsoProtocolError("OIDC id_token authorized party does not match")
    if not hmac_compare(str(claims.get("nonce") or ""), nonce):
        raise SsoProtocolError("OIDC id_token nonce does not match")
    return claims


def hmac_compare(left: str, right: str) -> bool:
    # Kept here to make every state/nonce comparison constant-time without
    # exposing protocol secrets to callers.
    import hmac

    return bool(left and right and hmac.compare_digest(left, right))


async def _fetch_userinfo(endpoint: str, access_token: str) -> dict[str, Any]:
    await _validated_public_https_url(endpoint, "userinfo_endpoint")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(
                endpoint,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
            response.raise_for_status()
            if len(response.content) > _MAX_OIDC_DOCUMENT_BYTES:
                raise SsoProtocolError("OIDC userinfo response is too large")
            payload = response.json()
    except SsoProtocolError:
        raise
    except Exception as exc:
        raise SsoProtocolError("OIDC userinfo retrieval failed") from exc
    if not isinstance(payload, dict):
        raise SsoProtocolError("OIDC userinfo response is invalid")
    return payload


async def resolve_oidc_identity(
    token_payload: dict[str, Any],
    metadata: dict[str, Any],
    config: SsoRuntimeConfig,
    *,
    nonce: str,
) -> OidcIdentity:
    claims = await validate_id_token(
        str(token_payload.get("id_token") or ""),
        metadata,
        config,
        nonce=nonce,
    )
    subject = str(claims.get("sub") or "").strip()
    userinfo: dict[str, Any] = {}
    endpoint = str(metadata.get("userinfo_endpoint") or "")
    access_token = str(token_payload.get("access_token") or "")
    if endpoint and access_token:
        userinfo = await _fetch_userinfo(endpoint, access_token)
        if str(userinfo.get("sub") or "").strip() != subject:
            raise SsoProtocolError("OIDC userinfo subject does not match id_token")

    if userinfo.get("email") and userinfo.get("email_verified") is False:
        raise SsoProtocolError("OIDC userinfo email is not verified")
    if not userinfo.get("email") and claims.get("email") and claims.get("email_verified") is False:
        raise SsoProtocolError("OIDC id_token email is not verified")

    email_candidates = (
        userinfo.get("email"),
        claims.get("email"),
        userinfo.get("preferred_username"),
        claims.get("preferred_username"),
    )
    email = next(
        (
            str(value).strip().lower()
            for value in email_candidates
            if value and _EMAIL_RE.fullmatch(str(value).strip())
        ),
        "",
    )
    if not email:
        raise SsoProtocolError("OIDC provider did not return an addressable email claim")
    name = str(
        userinfo.get("name")
        or claims.get("name")
        or userinfo.get("preferred_username")
        or claims.get("preferred_username")
        or email
    ).strip()[:255]
    return OidcIdentity(
        issuer=str(claims.get("iss") or "").strip(),
        subject=subject,
        email=email,
        name=name or email,
    )
