"""Private object storage for provider-owned ticket attachments.

Blob URLs and credentials never leave this module. Callers persist only a
deterministic blob key and serve bytes through Tickety OPS Tower's authorization layer.
"""

from __future__ import annotations

import os
import re
import hashlib
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


_CONTAINER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
# Azure permits up to 1,024 characters in a blob name.  All components below
# are ASCII after normalization, so this bound is also a byte bound.
_BLOB_NAME_MAX_CHARS = 1024
_BLOB_COMPONENT_MAX_CHARS = 144
_TARGET_IDENTITY_VERSION = "v2"


class AttachmentStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class AttachmentStorageConfig:
    provider: str
    account_url: str
    container: str
    connection_string: Optional[str]

    @property
    def configured(self) -> bool:
        return bool(
            self.provider == "azure_blob"
            and self.container
            and (self.account_url or self.connection_string)
        )

    @property
    def account_identity(self) -> str:
        """Return versioned, non-secret Azure target provenance.

        Account and container names are insufficient ownership proofs:
        private-cloud, emulator, and custom ``BlobEndpoint`` deployments can
        reuse both while addressing distinct endpoint authorities. Persist a
        versioned account-plus-authority identity instead. Credentials and all
        connection-string secret material stay out of this value.

        The version is intentional. Unversioned rows written by older releases
        are ambiguous and must fail closed instead of being silently
        reinterpreted as a new endpoint-bound target.
        """
        if self.connection_string:
            values = _connection_string_values(self.connection_string)
            account_name = values.get("accountname", "").strip().lower()
            endpoint = values.get("blobendpoint", "").strip()
            if endpoint:
                # BlobEndpoint overrides all default routing fields. Never
                # fall back to a guessed public endpoint when it is malformed
                # or non-HTTPS, because BlobServiceClient would use it.
                authority = _https_endpoint_authority(endpoint)
                if not authority:
                    return ""
            else:
                authority = ""
            if not endpoint and account_name:
                protocol = values.get("defaultendpointsprotocol", "https").strip().lower()
                # The app's managed-identity path accepts HTTPS only. A legacy
                # HTTP connection string cannot prove it addresses the same
                # remote target, so keep its provenance unproven as well.
                if protocol != "https":
                    return ""
                endpoint_suffix = values.get("endpointsuffix", "").strip().lower().strip(".")
                if endpoint_suffix and re.fullmatch(r"[a-z0-9.-]+", endpoint_suffix):
                    authority = f"{account_name}.blob.{endpoint_suffix}"
                else:
                    authority = f"{account_name}.blob.core.windows.net"
            if authority:
                return _target_identity(account_name or _account_name_from_authority(authority), authority)
            return ""
        authority = _https_endpoint_authority(self.account_url)
        if authority:
            return _target_identity(_account_name_from_authority(authority), authority)
        return ""


def _connection_string_values(connection_string: str) -> dict[str, str]:
    """Read only non-secret connection-string routing fields."""
    values: dict[str, str] = {}
    for part in connection_string.split(";"):
        key, separator, value = part.partition("=")
        if separator:
            values[key.strip().lower()] = value.strip()
    return values


def _https_endpoint_authority(endpoint: str) -> str:
    """Canonicalize a safe HTTPS endpoint authority without retaining a URL."""
    try:
        parsed = urlparse(endpoint)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return ""
    hostname = parsed.hostname.rstrip(".").lower()
    return f"{hostname}:{port}" if port is not None else hostname


def _account_name_from_authority(authority: str) -> str:
    # AccountName is display/provenance context only; the full authority is
    # the security boundary. This also supports local emulators with a
    # single-label hostname without relying on a connection-string secret.
    return authority.split(".", 1)[0].split(":", 1)[0]


def _target_identity(account_name: str, authority: str) -> str:
    if not account_name or not authority:
        return ""
    return f"{_TARGET_IDENTITY_VERSION}:{account_name}@{authority}"


def attachment_storage_config() -> AttachmentStorageConfig:
    return AttachmentStorageConfig(
        provider=(os.getenv("ATTACHMENT_STORAGE_PROVIDER") or "").strip().lower(),
        account_url=(os.getenv("AZURE_STORAGE_ACCOUNT_URL") or "").strip().rstrip("/"),
        container=(os.getenv("AZURE_STORAGE_CONTAINER") or "").strip().lower(),
        connection_string=(os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip() or None,
    )


def attachment_storage_configured() -> bool:
    return attachment_storage_config().configured


def attachment_storage_target_matches(
    *,
    storage_provider: Optional[str],
    storage_account_identity: Optional[str],
    storage_container: Optional[str],
    config: Optional[AttachmentStorageConfig] = None,
) -> bool:
    """Require a read to use the exact non-secret target that stored a blob.

    Blob keys are intentionally portable identifiers, not capabilities.  They
    must therefore never be looked up in a replacement account or container
    just because an operator changed the live storage configuration.  Rows
    written before target provenance existed are likewise unproven and remain
    fail-closed until explicitly repaired/re-copied.
    """
    target = config or attachment_storage_config()
    return bool(
        target.configured
        and storage_provider
        and storage_account_identity
        and storage_container
        and target.provider == storage_provider
        and target.account_identity == storage_account_identity
        and target.container == storage_container
    )


def attachment_max_bytes() -> int:
    try:
        value = int(os.getenv("ATTACHMENT_MAX_BYTES", str(50 * 1024 * 1024)))
    except (TypeError, ValueError):
        value = 50 * 1024 * 1024
    return max(1 * 1024 * 1024, min(value, 100 * 1024 * 1024))


def safe_blob_name(
    *,
    binding_id: str,
    provider_ticket_id: str,
    owner_type: str,
    owner_external_id: str,
    external_id: str,
    file_name: str,
) -> str:
    # Each display-friendly component is bounded for Azure path usability, but
    # a bound alone is not an identity boundary: two distinct provider values
    # can share the same first 180 normalized characters.  Bind a digest of
    # every original component into the key so a later retirement can never
    # delete another attachment merely because their readable prefixes match.
    identity_values = (
        str(binding_id or ""),
        str(provider_ticket_id or ""),
        str(owner_type or ""),
        str(owner_external_id or ""),
        str(external_id or ""),
        str(file_name or ""),
    )
    canonical_identity = "".join(
        f"{len(value)}:{value}" for value in identity_values
    )
    identity_suffix = hashlib.sha256(
        canonical_identity.encode("utf-8")
    ).hexdigest()

    def component(value: str, fallback: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
        cleaned = re.sub(r"\.{2,}", "_", cleaned)
        return (cleaned or fallback)[:_BLOB_COMPONENT_MAX_CHARS]

    blob_key = "/".join((
        "bindings",
        component(binding_id, "legacy"),
        "freshservice",
        "tickets",
        component(provider_ticket_id, "unknown"),
        component(owner_type, "ticket"),
        component(owner_external_id, "unknown"),
        f"{component(external_id, 'unknown')}--{identity_suffix}",
        component(file_name, "attachment"),
    ))
    # Keep the deployment-facing contract explicit: changing the component
    # constants above must never quietly reintroduce an Azure upload failure
    # for a provider's maximum-length identifiers.
    if len(blob_key) > _BLOB_NAME_MAX_CHARS:  # pragma: no cover - invariant guard
        raise AttachmentStorageError("azure_blob_name_too_long")
    return blob_key


class AzureBlobAttachmentStore:
    def __init__(self, config: Optional[AttachmentStorageConfig] = None):
        self.config = config or attachment_storage_config()
        if not self.config.configured:
            raise AttachmentStorageError("attachment_storage_not_configured")
        if not _CONTAINER_RE.fullmatch(self.config.container):
            raise AttachmentStorageError("azure_container_name_invalid")
        # A connection string selects its own service endpoint.  Refusing an
        # unprovable target here prevents an HTTP/malformed configuration from
        # uploading an object that cannot later be safely read or collected.
        if self.config.connection_string and not self.config.account_identity:
            raise AttachmentStorageError("azure_connection_string_endpoint_invalid")
        if self.config.account_url:
            if not _https_endpoint_authority(self.config.account_url):
                raise AttachmentStorageError("azure_account_url_invalid")
        self._service_client = None

    def _client(self):
        if self._service_client is not None:
            return self._service_client
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:
            raise AttachmentStorageError("azure_storage_sdk_unavailable") from exc
        if self.config.connection_string:
            self._service_client = BlobServiceClient.from_connection_string(
                self.config.connection_string
            )
        else:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:
                raise AttachmentStorageError("azure_identity_sdk_unavailable") from exc
            self._service_client = BlobServiceClient(
                account_url=self.config.account_url,
                credential=DefaultAzureCredential(),
            )
        return self._service_client

    def probe(self) -> None:
        self._client().get_container_client(
            self.config.container
        ).get_container_properties()

    def upload(self, blob_key: str, content: bytes, content_type: Optional[str]) -> None:
        try:
            from azure.storage.blob import ContentSettings
        except ImportError as exc:
            raise AttachmentStorageError("azure_storage_sdk_unavailable") from exc
        self._client().get_blob_client(
            container=self.config.container,
            blob=blob_key,
        ).upload_blob(
            content,
            # Copy attempts use a lease-token-derived immutable key.  Refuse
            # a write if that key already exists as a final remote boundary:
            # a duplicate/replayed request may fail and recover through the
            # durable provenance queue, but it can never replace bytes which
            # another attempt published.
            overwrite=False,
            content_settings=ContentSettings(
                content_type=content_type or "application/octet-stream"
            ),
            # Azure metadata keys must be valid C# identifiers; hyphens are
            # rejected with InvalidMetadata even when blob authorization is
            # otherwise correct.
            metadata={"managed_by": "tickety"},
        )

    def download(self, blob_key: str) -> bytes:
        return self._client().get_blob_client(
            container=self.config.container,
            blob=blob_key,
        ).download_blob().readall()

    def delete(self, blob_key: str) -> bool:
        """Remove one managed private blob and report whether it existed.

        A 404 is reported to the caller rather than flattened into success.
        A token-derived copy target can still be created by a request whose
        response arrives after its database lease was fenced; its durable GC
        intent must therefore remain live until the collector has observed
        and deleted that object at least once.

        A collector must never treat a deterministic path as ownership by
        itself.  Verify the upload marker and bind the delete to the observed
        ETag, so another writer cannot replace that path between the check and
        the remote delete.
        """
        try:
            from azure.core import MatchConditions

            blob_client = self._client().get_blob_client(
                container=self.config.container,
                blob=blob_key,
            )
            properties = blob_client.get_blob_properties()
            metadata = {
                str(key).lower(): str(value).lower()
                for key, value in (getattr(properties, "metadata", None) or {}).items()
            }
            if metadata.get("managed_by") != "tickety":
                raise AttachmentStorageError("azure_blob_not_managed_by_tickety")
            etag = getattr(properties, "etag", None)
            if not etag:
                raise AttachmentStorageError("azure_blob_etag_unavailable")
            blob_client.delete_blob(
                delete_snapshots="include",
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
            return True
        except ImportError as exc:
            raise AttachmentStorageError("azure_storage_sdk_unavailable") from exc
        except Exception as exc:
            status_code = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code == 404:
                return False
            raise
