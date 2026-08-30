import hashlib
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
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


class _FailingAttachmentAdapter:
    provider_name = "freshservice"

    async def download_attachment(self, _url, _max_bytes):
        error = RuntimeError("provider unavailable")
        error.response = SimpleNamespace(status_code=503)
        raise error


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
            "FRESHSERVICE_DOMAIN": "example.freshservice.com",
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
                "attachment_url": "https://example.freshservice.com/attachments/91",
            }],
        })

        self.assertEqual(len(parsed.description), 150_000)
        self.assertEqual(parsed.description_html, f"<p>{long_text}</p>")
        self.assertEqual(parsed.attachments[0].external_id, "91")
        self.assertEqual(parsed.attachments[0].name, "screenshot.png")

    def test_conversation_parser_retains_text_html_and_attachment_owner_data(self):
        adapter = FreshserviceAdapter({
            "FRESHSERVICE_DOMAIN": "example.freshservice.com",
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
                "attachment_url": "https://example.freshservice.com/attachments/92",
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
            download_url="https://example.freshservice.com/attachments/91",
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
            claim_checkpoints = []
            stored, errors = sync._sync_freshservice_attachment_backlog(
                self.db,
                adapter=_AttachmentAdapter(),
                binding_id="legacy",
                limit=2,
                claim_checkpoint=claim_checkpoints.append,
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
        self.assertEqual(claim_checkpoints, [True, True, False])

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

    def test_attachment_metadata_upsert_batches_existing_row_lookup(self):
        attachments = [
            ExternalAttachment(
                external_id=f"attachment-{index}",
                name=f"screenshot-{index}.png",
                content_type="image/png",
                size=123,
                download_url=f"https://example.freshservice.com/attachments/{index}",
            )
            for index in range(8)
        ]
        attachment_selects = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and "external_attachments" in normalized:
                attachment_selects.append(normalized)

        event.listen(self.db.bind, "before_cursor_execute", capture)
        try:
            with patch.dict(os.environ, {"ATTACHMENT_STORAGE_PROVIDER": ""}):
                sync._upsert_attachment_metadata(
                    self.db,
                    ticket=self.ticket,
                    owner_type="ticket",
                    owner_external_id="1151",
                    attachments=attachments,
                )
                self.db.commit()
        finally:
            event.remove(self.db.bind, "before_cursor_execute", capture)

        self.assertLessEqual(len(attachment_selects), 2, attachment_selects)
        self.assertEqual(self.db.query(ExternalAttachmentRecord).count(), 8)

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

    def test_failed_copy_uses_backoff_and_preserves_nested_http_status(self):
        attachment = ExternalAttachment(
            external_id="91",
            name="screenshot.png",
            content_type="image/png",
            size=123,
            download_url="https://example.freshservice.com/attachments/91",
        )
        storage_env = {
            "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
            "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
            "AZURE_STORAGE_CONTAINER": "tickety-attachments",
        }
        with patch.dict(os.environ, storage_env):
            sync._upsert_attachment_metadata(
                self.db,
                ticket=self.ticket,
                owner_type="ticket",
                owner_external_id="1151",
                attachments=[attachment],
            )
            self.db.commit()
            attempted_at = datetime.utcnow()
            stored, errors = sync._sync_freshservice_attachment_backlog(
                self.db,
                adapter=_FailingAttachmentAdapter(),
                binding_id="legacy",
                limit=2,
            )
            row = self.db.query(ExternalAttachmentRecord).one()
            first_attempts = row.attempts
            second_result = sync._sync_freshservice_attachment_backlog(
                self.db,
                adapter=_FailingAttachmentAdapter(),
                binding_id="legacy",
                limit=2,
            )

        self.assertEqual((stored, errors), (0, 1))
        self.assertEqual(second_result, (0, 0))
        self.assertEqual(row.attempts, first_attempts)
        self.assertEqual(
            row.last_error,
            "attachment_copy_failed:download:RuntimeError:http_503",
        )
        self.assertGreaterEqual(
            row.next_attempt_at,
            attempted_at + timedelta(seconds=59),
        )

    def test_rotated_attachment_id_retires_obsolete_failed_copy(self):
        storage_env = {
            "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
            "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
            "AZURE_STORAGE_CONTAINER": "tickety-attachments",
        }
        old = ExternalAttachment(
            external_id="old-id",
            name="Health Check Report.xls",
            content_type="application/vnd.ms-excel",
            size=184_320,
            download_url="https://example.attachments.freshservice.com/old",
        )
        replacement = ExternalAttachment(
            external_id="new-id",
            name=old.name,
            content_type=old.content_type,
            size=old.size,
            download_url="https://example.attachments.freshservice.com/new",
        )
        with patch.dict(os.environ, storage_env):
            sync._upsert_attachment_metadata(
                self.db,
                ticket=self.ticket,
                owner_type="conversation",
                owner_external_id="reply-1",
                attachments=[old],
            )
            self.db.commit()
            old_row = self.db.query(ExternalAttachmentRecord).one()
            old_row.storage_status = "error"
            old_row.attempts = 5
            old_row.last_error = "attachment_copy_failed:download:HTTPStatusError:http_403"
            self.db.commit()

            sync._upsert_attachment_metadata(
                self.db,
                ticket=self.ticket,
                owner_type="conversation",
                owner_external_id="reply-1",
                attachments=[replacement],
            )
            self.db.commit()
            replacement_row = self.db.query(ExternalAttachmentRecord).filter_by(
                external_id="new-id"
            ).one()
            replacement_row.storage_status = "stored"
            replacement_row.content_sha256 = "a" * 64
            replacement_row.stored_size = replacement.size
            replacement_row.stored_at = datetime.utcnow()
            self.db.commit()

            sync._upsert_attachment_metadata(
                self.db,
                ticket=self.ticket,
                owner_type="conversation",
                owner_external_id="reply-1",
                attachments=[replacement],
            )
            self.db.commit()

        self.db.refresh(old_row)
        self.assertEqual(old_row.storage_status, "superseded")
        self.assertIsNone(old_row.source_url)
        self.assertIsNone(old_row.last_error)
        self.assertIsNone(old_row.next_attempt_at)


if __name__ == "__main__":
    unittest.main()
