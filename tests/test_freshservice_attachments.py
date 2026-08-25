import hashlib
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import Base, ExternalAttachmentRecord, TicketRecord
from app.backend.attachment_storage import (
    AttachmentStorageConfig,
    AzureBlobAttachmentStore,
)
from app.backend.integrations import sync
from app.backend.integrations.freshservice import FreshserviceAdapter
from app.backend.schema import ExternalAttachment


class _AttachmentAdapter:
    provider_name = "freshservice"

    async def download_attachment(self, _url, max_bytes):
        content = b"original screenshot bytes"
        if len(content) > max_bytes:
            raise ValueError("too large")
        return content


class _Store:
    def __init__(self):
        self.uploads = []

    def upload(self, blob_key, content, content_type):
        self.uploads.append((blob_key, content, content_type))


class _BlobClient:
    def __init__(self):
        self.kwargs = None

    def upload_blob(self, _content, **kwargs):
        self.kwargs = kwargs


class _BlobServiceClient:
    def __init__(self, blob_client):
        self.blob_client = blob_client

    def get_blob_client(self, *, container, blob):
        self.container = container
        self.blob = blob
        return self.blob_client


class FreshserviceLosslessContentTests(unittest.TestCase):
    def test_ticket_parser_accepts_content_beyond_old_limit_and_keeps_html(self):
        adapter = FreshserviceAdapter({
            "FRESHSERVICE_DOMAIN": "acme.freshservice.com",
            "FRESHSERVICE_API_KEY": "test",
        })
        long_text = "x" * 150_000
        parsed = adapter._parse_ticket({
            "id": 1151,
            "subject": "Large source ticket",
            "description_text": long_text,
            "description": f"<p>{long_text}</p>",
            "priority": 2,
            "status": 2,
            "attachments": [{
                "id": 91,
                "name": "screenshot.png",
                "content_type": "image/png",
                "size": 123,
                "attachment_url": "https://acme.freshservice.com/attachments/91",
            }],
        })

        self.assertEqual(len(parsed.description), 150_000)
        self.assertEqual(parsed.description_html, f"<p>{long_text}</p>")
        self.assertEqual(parsed.attachments[0].external_id, "91")
        self.assertEqual(parsed.attachments[0].name, "screenshot.png")

    def test_conversation_parser_retains_text_html_and_attachment_owner_data(self):
        adapter = FreshserviceAdapter({
            "FRESHSERVICE_DOMAIN": "acme.freshservice.com",
            "FRESHSERVICE_API_KEY": "test",
        })
        parsed = adapter._parse_conversation({
            "id": 300,
            "body_text": "Please see the screenshot",
            "body": "<p>Please see the screenshot</p>",
            "attachments": [{
                "id": 92,
                "name": "reply.jpg",
                "content_type": "image/jpeg",
                "size": 456,
                "attachment_url": "https://acme.freshservice.com/attachments/92",
            }],
        })

        self.assertEqual(parsed.body, "Please see the screenshot")
        self.assertEqual(parsed.body_html, "<p>Please see the screenshot</p>")
        self.assertEqual(parsed.attachments[0].external_id, "92")


class AttachmentPersistenceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.ticket = TicketRecord(
            id="ticket-local-1",
            binding_id="legacy",
            external_source="freshservice",
            external_id="1151",
            subject="Attachment ticket",
            description="Complete body",
            reporter="requester@example.test",
            status="Open",
            workflow_status="Open",
            priority="P3",
            created_at=datetime(2026, 8, 25),
        )
        self.db.add(self.ticket)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_metadata_waits_without_storage_and_copies_idempotently_when_enabled(self):
        attachment = ExternalAttachment(
            external_id="91",
            name="Screenshot ../ original.png",
            content_type="image/png",
            size=len(b"original screenshot bytes"),
            download_url="https://acme.freshservice.com/attachments/91",
        )
        with patch.dict(os.environ, {"ATTACHMENT_STORAGE_PROVIDER": ""}):
            sync._upsert_attachment_metadata(
                self.db,
                ticket=self.ticket,
                owner_type="ticket",
                owner_external_id="1151",
                attachments=[attachment],
            )
            self.db.commit()
        row = self.db.query(ExternalAttachmentRecord).one()
        self.assertEqual(row.storage_status, "waiting_storage")
        self.assertNotIn("..", row.blob_key)

        store = _Store()
        storage_env = {
            "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
            "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
            "AZURE_STORAGE_CONTAINER": "tickety-attachments",
            "ATTACHMENT_MAX_BYTES": str(50 * 1024 * 1024),
        }
        with (
            patch.dict(os.environ, storage_env),
            patch.object(sync, "AzureBlobAttachmentStore", return_value=store),
        ):
            stored, errors = sync._sync_freshservice_attachment_backlog(
                self.db,
                adapter=_AttachmentAdapter(),
                binding_id="legacy",
                limit=2,
            )

        self.db.refresh(row)
        self.assertEqual((stored, errors), (1, 0))
        self.assertEqual(row.storage_status, "stored")
        self.assertIsNone(row.source_url)
        self.assertEqual(
            row.content_sha256,
            hashlib.sha256(b"original screenshot bytes").hexdigest(),
        )
        self.assertEqual(len(store.uploads), 1)

        with (
            patch.dict(os.environ, storage_env),
            patch.object(sync, "AzureBlobAttachmentStore", return_value=store),
        ):
            stored, errors = sync._sync_freshservice_attachment_backlog(
                self.db,
                adapter=_AttachmentAdapter(),
                binding_id="legacy",
                limit=2,
            )
        self.assertEqual((stored, errors), (0, 0))
        self.assertEqual(len(store.uploads), 1)

    def test_azure_upload_uses_valid_metadata_identifier(self):
        blob_client = _BlobClient()
        store = AzureBlobAttachmentStore(AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.core.windows.net",
            container="tickety-attachments",
            connection_string=None,
        ))
        store._service_client = _BlobServiceClient(blob_client)

        store.upload("ticket/screenshot.png", b"image", "image/png")

        self.assertEqual(blob_client.kwargs["metadata"], {"managed_by": "tickety"})


if __name__ == "__main__":
    unittest.main()
