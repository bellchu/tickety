import hashlib
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import main
from app.backend.database import (
    Base,
    ExternalAttachmentRecord,
    SessionRecord,
    TicketRecord,
    UserRecord,
    get_db,
)
from app.backend.attachment_storage import (
    AttachmentStorageError,
    AttachmentStorageConfig,
    AzureBlobAttachmentStore,
    safe_blob_name,
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


class _ManagedBlobClient:
    def __init__(self, *, metadata, etag='"managed-etag"'):
        self.metadata = metadata
        self.etag = etag
        self.delete_kwargs = None

    def get_blob_properties(self):
        return SimpleNamespace(metadata=self.metadata, etag=self.etag)

    def delete_blob(self, **kwargs):
        self.delete_kwargs = kwargs


class _DownloadStore:
    def __init__(self):
        self.downloads = []

    def download(self, blob_key):
        self.downloads.append(blob_key)
        return b"stored attachment bytes"


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

    def test_blob_key_preserves_identity_after_normalized_prefix_collision(self):
        shared_prefix = "external-attachment-" + ("x" * 220)
        first = safe_blob_name(
            binding_id="legacy",
            provider_ticket_id="1151",
            owner_type="ticket",
            owner_external_id="1151",
            external_id=f"{shared_prefix}-one",
            file_name="report.pdf",
        )
        second = safe_blob_name(
            binding_id="legacy",
            provider_ticket_id="1151",
            owner_type="ticket",
            owner_external_id="1151",
            external_id=f"{shared_prefix}-two",
            file_name="report.pdf",
        )

        self.assertNotEqual(first, second)
        self.assertIn("--", first.rsplit("/", 2)[-2])
        self.assertNotIn("..", first)

    def test_blob_key_stays_within_azure_limit_for_maximum_provider_identifiers(self):
        blob_key = safe_blob_name(
            binding_id="b" * 10_000,
            provider_ticket_id="t" * 10_000,
            owner_type="o" * 10_000,
            owner_external_id="r" * 10_000,
            external_id="e" * 10_000,
            file_name="f" * 10_000,
        )

        self.assertLessEqual(len(blob_key), 1024)
        self.assertEqual(len(blob_key.rsplit("/", 2)[-2].rsplit("--", 1)[-1]), 64)

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
        self.assertFalse(blob_client.kwargs["overwrite"])

    def test_azure_delete_requires_managed_marker_and_observed_etag(self):
        from azure.core import MatchConditions

        managed_client = _ManagedBlobClient(metadata={"managed_by": "tickety"})
        store = AzureBlobAttachmentStore(AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.core.windows.net",
            container="tickety-attachments",
            connection_string=None,
        ))
        store._service_client = _BlobServiceClient(managed_client)

        self.assertTrue(store.delete("ticket/screenshot.png"))

        self.assertEqual(managed_client.delete_kwargs, {
            "delete_snapshots": "include",
            "etag": '"managed-etag"',
            "match_condition": MatchConditions.IfNotModified,
        })

        unmanaged_client = _ManagedBlobClient(metadata={"managed_by": "other"})
        store._service_client = _BlobServiceClient(unmanaged_client)
        with self.assertRaisesRegex(AttachmentStorageError, "not_managed"):
            store.delete("ticket/screenshot.png")
        self.assertIsNone(unmanaged_client.delete_kwargs)

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


class AttachmentDownloadRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            db.add(TicketRecord(
                id="ticket-attachment-download",
                binding_id="legacy",
                external_source="freshservice",
                external_id="1151",
                subject="Stored attachment",
                description="Attachment test ticket",
                reporter="requester@example.test",
                status="Open",
                workflow_status="Open",
                priority="P3",
            ))
            db.add(ExternalAttachmentRecord(
                id="attachment-download",
                binding_id="legacy",
                provider="freshservice",
                ticket_id="ticket-attachment-download",
                provider_ticket_id="1151",
                owner_type="ticket",
                owner_external_id="1151",
                external_id="91",
                file_name="report.pdf",
                content_type="application/pdf",
                blob_key="bindings/legacy/report.pdf",
                storage_status="stored",
                storage_provider="azure_blob",
                storage_account_identity="v2:tickety@tickety.blob.core.windows.net",
                storage_container="tickety-attachments",
            ))
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        main.app.dependency_overrides[main.get_authenticated_user] = lambda: UserRecord(
            id="attachment-agent",
            name="Attachment Agent",
            role="agent",
            is_active=True,
        )
        self.auth_patch = patch.object(
            main, "_auth_required_for_request", return_value=False
        )
        self.auth_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_stored_attachment_download_is_offloaded_without_changing_response(self):
        store = _DownloadStore()
        offloads = []
        storage_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.core.windows.net",
            container="tickety-attachments",
            connection_string=None,
        )

        async def capture_offload(function, *args, **kwargs):
            offloads.append((function, args, kwargs))
            return function(*args, **kwargs)

        with (
            patch.dict(os.environ, {
                "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
                "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
                "AZURE_STORAGE_CONTAINER": "tickety-attachments",
            }),
            patch.object(
                main, "attachment_storage_config", return_value=storage_config,
            ) as config_loader,
            patch.object(main, "AzureBlobAttachmentStore", return_value=store) as factory,
            patch.object(main.asyncio, "to_thread", side_effect=capture_offload),
        ):
            response = self.client.get(
                "/tickets/ticket-attachment-download/attachments/attachment-download"
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, b"stored attachment bytes")
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("attachment; filename=\"report.pdf\"", response.headers["content-disposition"])
        self.assertEqual(store.downloads, ["bindings/legacy/report.pdf"])
        self.assertEqual(len(offloads), 1)
        self.assertEqual(offloads[0][0], store.download)
        self.assertEqual(offloads[0][1], ("bindings/legacy/report.pdf",))
        config_loader.assert_called_once_with()
        factory.assert_called_once_with(storage_config)

    def test_stored_attachment_never_reads_same_key_from_reconfigured_target(self):
        store = _DownloadStore()
        with (
            patch.dict(os.environ, {
                "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
                "AZURE_STORAGE_ACCOUNT_URL": "https://other.blob.core.windows.net",
                "AZURE_STORAGE_CONTAINER": "other-attachments",
            }),
            patch.object(main, "AzureBlobAttachmentStore", return_value=store) as factory,
        ):
            response = self.client.get(
                "/tickets/ticket-attachment-download/attachments/attachment-download"
            )

        self.assertEqual(response.status_code, 503, response.text)
        factory.assert_not_called()
        self.assertEqual(store.downloads, [])


class TerminalAttachmentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db:
            now = datetime.utcnow()
            db.add_all([
                UserRecord(
                    id="attachment-admin",
                    name="Attachment Admin",
                    role="admin",
                    is_active=True,
                ),
                UserRecord(
                    id="attachment-supervisor",
                    name="Attachment Supervisor",
                    role="supervisor",
                    is_active=True,
                ),
                SessionRecord(
                    token_hash=main.session_token_digest("attachment-admin-session"),
                    user_id="attachment-admin",
                    expires_at=now + timedelta(hours=1),
                ),
                SessionRecord(
                    token_hash=main.session_token_digest("attachment-supervisor-session"),
                    user_id="attachment-supervisor",
                    expires_at=now + timedelta(hours=1),
                ),
            ])
            db.add(TicketRecord(
                id="ticket-terminal-attachment",
                binding_id="legacy",
                external_source="freshservice",
                external_id="5150",
                subject="Terminal attachment",
                description="Attachment recovery test",
                reporter="requester@example.test",
                status="Open",
                workflow_status="Open",
                priority="P3",
            ))
            db.add(ExternalAttachmentRecord(
                id="attachment-terminal",
                binding_id="legacy",
                provider="freshservice",
                ticket_id="ticket-terminal-attachment",
                provider_ticket_id="5150",
                owner_type="ticket",
                owner_external_id="5150",
                external_id="terminal-91",
                file_name="terminal.png",
                content_type="image/png",
                declared_size=len(b"original screenshot bytes"),
                source_url="https://example.freshservice.com/attachments/terminal-91",
                blob_key="bindings/legacy/terminal.png",
                storage_status="error",
                attempts=5,
                last_error="attachment_copy_failed:download:RuntimeError:http_503",
            ))
            db.commit()

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.auth_patch = patch.object(
            main, "_auth_required_for_request", return_value=False
        )
        self.auth_patch.start()
        self.session_local_patch = patch.object(
            main, "SessionLocal", self.session_factory
        )
        self.session_local_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.session_local_patch.stop()
        self.auth_patch.stop()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def _as_role(self, role):
        self.client.cookies.set(main.SESSION_COOKIE, f"attachment-{role}-session")

    def test_terminal_failure_is_excluded_and_normal_metadata_sync_cannot_reset_it(self):
        self._as_role("admin")
        with self.session_factory() as db:
            with patch.dict(os.environ, {
                "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
                "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
                "AZURE_STORAGE_CONTAINER": "tickety-attachments",
            }):
                self.assertEqual(
                    sync._sync_freshservice_attachment_backlog(
                        db,
                        adapter=_AttachmentAdapter(),
                        binding_id="legacy",
                        limit=2,
                    ),
                    (0, 0),
                )
                ticket = db.query(TicketRecord).filter_by(
                    id="ticket-terminal-attachment"
                ).one()
                sync._upsert_attachment_metadata(
                    db,
                    ticket=ticket,
                    owner_type="ticket",
                    owner_external_id="5150",
                    attachments=[ExternalAttachment(
                        external_id="terminal-91",
                        name="terminal.png",
                        content_type="image/png",
                        size=len(b"original screenshot bytes"),
                        download_url="https://example.freshservice.com/attachments/rotated-url",
                    )],
                )
                db.commit()
                row = db.query(ExternalAttachmentRecord).filter_by(
                    id="attachment-terminal"
                ).one()
                self.assertEqual((row.storage_status, row.attempts), ("error", 5))
                self.assertEqual(
                    row.source_url,
                    "https://example.freshservice.com/attachments/rotated-url",
                )

    def test_only_admin_can_requeue_terminal_copy_then_success_cleans_source_and_audits(self):
        self._as_role("supervisor")
        denied = self.client.post(
            "/admin/sync/attachments/attachment-terminal/requeue",
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        self._as_role("admin")
        storage_env = {
            "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
            "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
            "AZURE_STORAGE_CONTAINER": "tickety-attachments",
        }
        with patch.dict(os.environ, storage_env):
            response = self.client.post(
                "/admin/sync/attachments/attachment-terminal/requeue",
                headers={"Origin": "http://testserver"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "action": "attachment_requeue",
            "attachment_id": "attachment-terminal",
            "status": "pending",
        })

        store = _Store()
        with (
            self.session_factory() as db,
            patch.dict(os.environ, storage_env),
            patch.object(sync, "AzureBlobAttachmentStore", return_value=store),
        ):
            row = db.query(ExternalAttachmentRecord).filter_by(
                id="attachment-terminal"
            ).one()
            self.assertEqual((row.storage_status, row.attempts), ("pending", 0))
            self.assertIsNone(row.last_error)
            audit = db.query(main.TicketAuditLogRecord).filter_by(
                ticket_id="ticket-terminal-attachment",
                field="attachment_copy_requeue",
            ).one()
            self.assertEqual(audit.old_value, "error:5_attempts")
            self.assertEqual(audit.new_value, "pending:attempts_reset")
            self.assertEqual(audit.changed_by, "Attachment Admin")
            self.assertEqual(
                sync._sync_freshservice_attachment_backlog(
                    db,
                    adapter=_AttachmentAdapter(),
                    binding_id="legacy",
                    limit=1,
                ),
                (1, 0),
            )
            db.refresh(row)
            self.assertEqual(row.storage_status, "stored")
            self.assertIsNone(row.source_url)
            self.assertEqual(len(store.uploads), 1)


if __name__ == "__main__":
    unittest.main()
