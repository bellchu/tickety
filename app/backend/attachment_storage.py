"""Private object storage for provider-owned ticket attachments.

Blob URLs and credentials never leave this module. Callers persist only a
deterministic blob key and serve bytes through Tickety's authorization layer.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


_CONTAINER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")


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


def attachment_storage_config() -> AttachmentStorageConfig:
    return AttachmentStorageConfig(
        provider=(os.getenv("ATTACHMENT_STORAGE_PROVIDER") or "").strip().lower(),
        account_url=(os.getenv("AZURE_STORAGE_ACCOUNT_URL") or "").strip().rstrip("/"),
        container=(os.getenv("AZURE_STORAGE_CONTAINER") or "").strip().lower(),
        connection_string=(os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip() or None,
    )


def attachment_storage_configured() -> bool:
    return attachment_storage_config().configured


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
    def component(value: str, fallback: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
        cleaned = re.sub(r"\.{2,}", "_", cleaned)
        return (cleaned or fallback)[:180]

    return "/".join((
        "bindings",
        component(binding_id, "legacy"),
        "freshservice",
        "tickets",
        component(provider_ticket_id, "unknown"),
        component(owner_type, "ticket"),
        component(owner_external_id, "unknown"),
        component(external_id, "unknown"),
        component(file_name, "attachment"),
    ))


class AzureBlobAttachmentStore:
    def __init__(self, config: Optional[AttachmentStorageConfig] = None):
        self.config = config or attachment_storage_config()
        if not self.config.configured:
            raise AttachmentStorageError("attachment_storage_not_configured")
        if not _CONTAINER_RE.fullmatch(self.config.container):
            raise AttachmentStorageError("azure_container_name_invalid")
        if self.config.account_url:
            parsed = urlparse(self.config.account_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not parsed.hostname.endswith(".blob.core.windows.net")
            ):
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
            overwrite=True,
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
