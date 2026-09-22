import asyncio
import hashlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.integrations import sync
from app.backend import attachment_gc
from app.backend.database import (
    AttachmentBlobDeletionRecord,
    Base,
    ExternalAttachmentRecord,
    TicketRecord,
)
from app.backend.attachment_storage import (
    AttachmentStorageConfig,
    attachment_storage_config,
)


_STORAGE_ENV = {
    "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
    "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
    "AZURE_STORAGE_CONTAINER": "tickety-attachments",
}


class _Store:
    uploads = []
    configs = []

    def __init__(self, config=None):
        self.config = config
        self.configs.append(config)

    def upload(self, blob_key, content, content_type):
        self.uploads.append((blob_key, content, content_type))


class _Adapter:
    provider_name = "freshservice"

    def __init__(self, before_download=None):
        self.before_download = before_download
        self.downloads = []

    async def download_attachment(self, url, _max_bytes):
        self.downloads.append(url)
        if self.before_download is not None:
            self.before_download()
        return b"attachment bytes"


class AttachmentCopyLeaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        with self.Session() as db:
            db.add(TicketRecord(
                id="copy-lease-ticket",
                binding_id="legacy",
                external_source="freshservice",
                external_id="1151",
                subject="Copy lease",
                description="lease fencing test",
                reporter="requester@example.test",
                status="Open",
                workflow_status="Open",
                priority="P3",
            ))
            db.add(ExternalAttachmentRecord(
                id="copy-lease-attachment",
                binding_id="legacy",
                provider="freshservice",
                ticket_id="copy-lease-ticket",
                provider_ticket_id="1151",
                owner_type="ticket",
                owner_external_id="1151",
                external_id="91",
                file_name="report.pdf",
                content_type="application/pdf",
                declared_size=len(b"attachment bytes"),
                source_url="https://example.freshservice.com/attachments/91",
                blob_key="bindings/legacy/1151/91.pdf",
                storage_status="pending",
            ))
            db.commit()
        _Store.uploads = []
        _Store.configs = []

    def tearDown(self):
        self.engine.dispose()

    def _claim(self, db):
        return sync._claim_next_attachment_copy(
            db,
            binding_id="legacy",
            provider="freshservice",
            now=datetime.utcnow(),
        )

    def test_live_row_lease_blocks_second_owner_and_late_owner_is_fenced(self):
        first_db = self.Session()
        second_db = self.Session()
        try:
            first = self._claim(first_db)
            self.assertIsNotNone(first)
            self.assertIsNone(self._claim(second_db))

            row = first_db.query(ExternalAttachmentRecord).one()
            row.copy_lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
            first_db.commit()
            second = self._claim(second_db)
            self.assertIsNotNone(second)
            self.assertNotEqual(first.token, second.token)

            with patch.dict(os.environ, _STORAGE_ENV):
                outcome = sync._complete_attachment_copy(
                    first_db, first, b"attachment bytes", attachment_storage_config()
                )
            self.assertEqual(outcome, "fenced")
            second_db.expire_all()
            row = second_db.query(ExternalAttachmentRecord).one()
            self.assertEqual(row.copy_lease_token, second.token)
            self.assertEqual(row.storage_status, "pending")
        finally:
            first_db.close()
            second_db.close()

    def test_expired_upload_cannot_overwrite_successor_immutable_blob(self):
        """A blocked Azure call may return after its row lease is replaced.

        The replacement must publish a different immutable candidate.  This
        exercises the physical object-store boundary, not merely the later DB
        token predicate: the old upload deliberately resumes only after B has
        committed its final attachment key.
        """
        test_case = self
        objects = {}
        successor = {}
        first_upload_started = {"value": False}
        cleanup_while_first_upload_is_late = []

        class _ImmutableStore:
            def __init__(self, config=None):
                self.config = config

            def upload(self, blob_key, content, _content_type):
                if not first_upload_started["value"]:
                    # Hold A immediately before its physical object write.
                    # B must use the same overwrite-protecting store, publish,
                    # and survive a GC sweep before A is allowed to resume.
                    first_upload_started["value"] = True
                    with test_case.Session() as replacement_db:
                        row = replacement_db.query(ExternalAttachmentRecord).one()
                        row.copy_lease_expires_at = (
                            datetime.utcnow() - timedelta(seconds=1)
                        )
                        replacement_db.commit()
                        claim_b = sync._claim_next_attachment_copy(
                            replacement_db,
                            binding_id="legacy",
                            provider="freshservice",
                            now=datetime.utcnow(),
                        )
                        test_case.assertIsNotNone(claim_b)
                        test_case.assertTrue(sync._mark_attachment_copy_upload_started(
                            replacement_db, claim_b, self.config,
                        ))
                        candidate_b = replacement_db.query(ExternalAttachmentRecord).one()
                        candidate_b_key = candidate_b.copy_upload_blob_key
                        _ImmutableStore(self.config).upload(
                            candidate_b_key,
                            b"B" * len(content),
                            _content_type,
                        )
                        test_case.assertEqual(
                            sync._complete_attachment_copy(
                                replacement_db,
                                claim_b,
                                b"B" * len(content),
                                self.config,
                            ),
                            "stored",
                        )
                        stale_cleanup = replacement_db.query(
                            AttachmentBlobDeletionRecord
                        ).one()
                        stale_cleanup.next_attempt_at = (
                            datetime.utcnow() - timedelta(seconds=1)
                        )
                        replacement_db.commit()
                        successor["candidate"] = candidate_b_key

                    with (
                        patch.object(attachment_gc, "SessionLocal", test_case.Session),
                        patch.object(attachment_gc, "AzureBlobAttachmentStore", _ImmutableStore),
                    ):
                        cleanup_while_first_upload_is_late.append(
                            attachment_gc.collect_superseded_attachment_blobs(limit=1)
                        )

                # Model Azure's create-only boundary: another write to the
                # same candidate is rejected instead of replacing its bytes.
                if blob_key in objects:
                    raise RuntimeError("azure_blob_already_exists")
                objects[blob_key] = content

            def delete(self, blob_key):
                if blob_key not in objects:
                    return False
                del objects[blob_key]
                return True

        with (
            self.Session() as first_db,
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(sync, "AzureBlobAttachmentStore", _ImmutableStore),
        ):
            self.assertEqual(
                sync._sync_freshservice_attachment_backlog(
                    first_db, adapter=_Adapter(), binding_id="legacy", limit=1,
                ),
                (0, 0),
            )

        self.assertIn("candidate", successor)
        self.assertEqual(
            cleanup_while_first_upload_is_late,
            [{"deleted": 0, "failed": 0, "cancelled": 0, "deferred": 1}],
        )

        with self.Session() as verify_db:
            row = verify_db.query(ExternalAttachmentRecord).one()
            stale_cleanup = verify_db.query(AttachmentBlobDeletionRecord).one()
            stale_key = stale_cleanup.blob_key
            self.assertEqual(row.storage_status, "stored")
            self.assertEqual(row.blob_key, successor["candidate"])
            self.assertEqual(row.content_sha256, hashlib.sha256(
                b"B" * len(b"attachment bytes")
            ).hexdigest())
            self.assertEqual(objects[row.blob_key], b"B" * len(b"attachment bytes"))
            self.assertNotEqual(row.blob_key, stale_key)
            self.assertIn(stale_key, objects)
            self.assertEqual(stale_cleanup.status, "pending")
            self.assertIsNotNone(stale_cleanup.next_attempt_at)
            stale_cleanup.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            verify_db.commit()

        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "SessionLocal", self.Session),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _ImmutableStore),
        ):
            self.assertEqual(
                attachment_gc.collect_superseded_attachment_blobs(limit=1),
                {"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0},
            )
        self.assertNotIn(stale_key, objects)

    def test_metadata_change_discards_old_result_without_poisoning_replacement(self):
        db = self.Session()
        try:
            claim = self._claim(db)
            row = db.query(ExternalAttachmentRecord).one()
            row.source_url = "https://example.freshservice.com/attachments/replacement"
            row.declared_size = 99
            db.commit()

            with patch.dict(os.environ, _STORAGE_ENV):
                outcome = sync._complete_attachment_copy(
                    db, claim, b"attachment bytes", attachment_storage_config()
                )
            self.assertEqual(outcome, "discarded")
            db.expire_all()
            row = db.query(ExternalAttachmentRecord).one()
            self.assertEqual(row.storage_status, "pending")
            self.assertEqual(row.source_url, "https://example.freshservice.com/attachments/replacement")
            self.assertIsNone(row.copy_lease_token)
            self.assertEqual(row.attempts, 0)
        finally:
            db.close()

    def test_retired_during_upload_stays_retired_and_queues_blob_cleanup(self):
        db = self.Session()
        try:
            claim = self._claim(db)
            row = db.query(ExternalAttachmentRecord).one()
            row.storage_status = "superseded"
            row.source_url = None
            db.commit()

            with patch.dict(os.environ, _STORAGE_ENV):
                outcome = sync._complete_attachment_copy(
                    db, claim, b"attachment bytes", attachment_storage_config()
                )
            self.assertEqual(outcome, "retired")
            db.expire_all()
            row = db.query(ExternalAttachmentRecord).one()
            task = db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(row.storage_status, "superseded")
            self.assertEqual(task.blob_key, row.blob_key)
            self.assertEqual(task.status, "pending")
        finally:
            db.close()

    def test_resurrected_row_queues_late_uploads_old_immutable_key(self):
        db = self.Session()
        try:
            claim = self._claim(db)
            old_key = claim.blob_key
            row = db.query(ExternalAttachmentRecord).one()
            row.storage_status = "pending"
            row.source_url = "https://example.freshservice.com/attachments/revived"
            row.blob_key = f"{old_key}.revived-immutable"
            row.storage_provider = None
            row.storage_account_identity = None
            row.storage_container = None
            db.commit()

            with patch.dict(os.environ, _STORAGE_ENV):
                outcome = sync._complete_attachment_copy(
                    db, claim, b"attachment bytes", attachment_storage_config()
                )

            self.assertEqual(outcome, "discarded")
            db.expire_all()
            row = db.query(ExternalAttachmentRecord).one()
            task = db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(row.storage_status, "pending")
            self.assertEqual(row.blob_key, f"{old_key}.revived-immutable")
            self.assertEqual(task.blob_key, old_key)
            self.assertEqual(task.status, "pending")
            self.assertEqual(task.storage_provider, "azure_blob")
            self.assertEqual(task.storage_account_identity, "v2:tickety@tickety.blob.core.windows.net")
            self.assertEqual(task.storage_container, "tickety-attachments")
        finally:
            db.close()

    def test_binding_claim_loss_after_upload_finalizes_retired_blob_cleanup(self):
        test_case = self
        observed_upload_provenance = []

        class _SupersedingStore(_Store):
            def upload(self, blob_key, content, content_type):
                super().upload(blob_key, content, content_type)
                with test_case.Session() as other_db:
                    row = other_db.query(ExternalAttachmentRecord).one()
                    observed_upload_provenance.append((
                        row.copy_upload_blob_key,
                        row.copy_upload_storage_provider,
                        row.copy_upload_storage_account_identity,
                        row.copy_upload_storage_container,
                        row.copy_upload_started_at,
                    ))
                    row.storage_status = "superseded"
                    row.source_url = None
                    other_db.commit()

        with (
            self.Session() as db,
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(sync, "AzureBlobAttachmentStore", _SupersedingStore),
        ):
            def lose_binding_claim(renew):
                if not renew:
                    # _require_freshservice_run_owner rolls back on this path;
                    # mirror that boundary before the uploaded-result finalizer.
                    db.rollback()
                    raise sync._FreshserviceRunClaimLost("binding replaced")

            with self.assertRaises(sync._FreshserviceRunClaimLost):
                sync._sync_freshservice_attachment_backlog(
                    db,
                    adapter=_Adapter(),
                    binding_id="legacy",
                    limit=1,
                    claim_checkpoint=lose_binding_claim,
                )

        with self.Session() as verify_db:
            row = verify_db.query(ExternalAttachmentRecord).one()
            task = verify_db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(row.storage_status, "superseded")
            self.assertIsNone(row.copy_lease_token)
            self.assertEqual(task.attachment_id, row.id)
            self.assertEqual(task.blob_key, row.blob_key)
            self.assertEqual(task.status, "pending")
            self.assertEqual(task.storage_provider, "azure_blob")
            self.assertEqual(task.storage_account_identity, "v2:tickety@tickety.blob.core.windows.net")
            self.assertEqual(task.storage_container, "tickety-attachments")
            self.assertEqual(observed_upload_provenance[0][:4], (
                task.blob_key,
                task.storage_provider,
                task.storage_account_identity,
                task.storage_container,
            ))
            self.assertIsNotNone(observed_upload_provenance[0][4])

    def test_binding_claim_loss_after_upload_queues_replaced_snapshot_key(self):
        test_case = self
        original_key = "bindings/legacy/1151/91.pdf"

        class _ResurrectingStore(_Store):
            def upload(self, blob_key, content, content_type):
                super().upload(blob_key, content, content_type)
                with test_case.Session() as other_db:
                    row = other_db.query(ExternalAttachmentRecord).one()
                    row.source_url = "https://example.freshservice.com/attachments/revived"
                    row.blob_key = f"{original_key}.revived-immutable"
                    other_db.commit()

        with (
            self.Session() as db,
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(sync, "AzureBlobAttachmentStore", _ResurrectingStore),
        ):
            def lose_binding_claim(renew):
                if not renew:
                    db.rollback()
                    raise sync._FreshserviceRunClaimLost("binding replaced")

            with self.assertRaises(sync._FreshserviceRunClaimLost):
                sync._sync_freshservice_attachment_backlog(
                    db,
                    adapter=_Adapter(),
                    binding_id="legacy",
                    limit=1,
                    claim_checkpoint=lose_binding_claim,
                )

        with self.Session() as verify_db:
            row = verify_db.query(ExternalAttachmentRecord).one()
            task = verify_db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(row.storage_status, "pending")
            self.assertEqual(row.blob_key, f"{original_key}.revived-immutable")
            self.assertIsNone(row.copy_lease_token)
            self.assertEqual(row.attempts, 0)
            self.assertNotEqual(task.blob_key, original_key)
            self.assertIn(".copy-", task.blob_key)
            self.assertEqual(task.status, "pending")
            self.assertEqual(task.storage_provider, "azure_blob")
            self.assertEqual(task.storage_account_identity, "v2:tickety@tickety.blob.core.windows.net")
            self.assertEqual(task.storage_container, "tickety-attachments")

    def test_binding_loss_finalizer_failure_records_ambiguous_upload_cleanup(self):
        with (
            self.Session() as db,
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(sync, "AzureBlobAttachmentStore", _Store),
            patch.object(
                sync,
                "_complete_attachment_copy",
                side_effect=RuntimeError("completion transaction lost"),
            ),
        ):
            def lose_binding_claim(renew):
                if not renew:
                    db.rollback()
                    raise sync._FreshserviceRunClaimLost("binding replaced")

            with self.assertRaises(sync._FreshserviceRunClaimLost):
                sync._sync_freshservice_attachment_backlog(
                    db,
                    adapter=_Adapter(),
                    binding_id="legacy",
                    limit=1,
                    claim_checkpoint=lose_binding_claim,
                )

        with self.Session() as verify_db:
            row = verify_db.query(ExternalAttachmentRecord).one()
            task = verify_db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(row.storage_status, "error")
            self.assertIsNone(row.copy_lease_token)
            self.assertEqual(task.blob_key, row.copy_upload_blob_key)
            self.assertEqual(task.status, "pending")

    def test_ambiguous_target_rekeys_before_copying_to_new_storage_target(self):
        storage_a = {
            **_STORAGE_ENV,
            "AZURE_STORAGE_ACCOUNT_URL": "https://account-a.blob.core.windows.net",
        }
        storage_b = {
            **_STORAGE_ENV,
            "AZURE_STORAGE_ACCOUNT_URL": "https://account-b.blob.core.windows.net",
        }

        class _TimeoutAfterAcceptStore:
            def __init__(self, config=None):
                self.config = config

            def upload(self, _blob_key, _content, _content_type):
                raise TimeoutError("Azure response lost after accept")

        class _RecordingStore:
            uploads = []

            def __init__(self, config=None):
                self.config = config

            def upload(self, blob_key, content, content_type):
                self.uploads.append((blob_key, content, content_type, self.config))

        class _DeletingStore:
            deleted = []

            def __init__(self, config=None):
                self.config = config

            def delete(self, blob_key):
                self.deleted.append((blob_key, self.config.account_identity))

        with self.Session() as db:
            with (
                patch.dict(os.environ, storage_a),
                patch.object(sync, "AzureBlobAttachmentStore", _TimeoutAfterAcceptStore),
            ):
                self.assertEqual(
                    sync._sync_freshservice_attachment_backlog(
                        db, adapter=_Adapter(), binding_id="legacy", limit=1,
                    ),
                    (0, 1),
                )
            row = db.query(ExternalAttachmentRecord).one()
            old_key = row.blob_key
            old_target = row.copy_upload_storage_account_identity
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

            with (
                patch.dict(os.environ, storage_b),
                patch.object(sync, "AzureBlobAttachmentStore", _RecordingStore),
            ):
                self.assertEqual(
                    sync._sync_freshservice_attachment_backlog(
                        db, adapter=_Adapter(), binding_id="legacy", limit=2,
                    ),
                    (1, 0),
                )

        with self.Session() as verify_db:
            row = verify_db.query(ExternalAttachmentRecord).one()
            task = verify_db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(row.storage_status, "stored")
            self.assertNotEqual(row.blob_key, old_key)
            self.assertIn(".copy-", row.blob_key)
            self.assertEqual(row.storage_account_identity, "v2:account-b@account-b.blob.core.windows.net")
            self.assertNotEqual(task.blob_key, old_key)
            self.assertIn(".copy-", task.blob_key)
            self.assertEqual(task.storage_account_identity, old_target)
            self.assertEqual(_RecordingStore.uploads[0][0], row.blob_key)
            self.assertEqual(
                _RecordingStore.uploads[0][3].account_identity,
                row.storage_account_identity,
            )
            retired_key = task.blob_key
            task.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            verify_db.commit()

        with (
            patch.dict(os.environ, storage_a),
            patch.object(attachment_gc, "SessionLocal", self.Session),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            self.assertEqual(
                attachment_gc.collect_superseded_attachment_blobs(limit=1),
                {"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0},
            )
        self.assertEqual(_DeletingStore.deleted, [(retired_key, old_target)])

    def test_timeout_after_accepted_upload_defers_cleanup_until_superseded(self):
        class _TimeoutAfterAcceptStore:
            uploads = []

            def __init__(self, config=None):
                self.config = config

            def upload(self, blob_key, content, content_type):
                self.uploads.append((blob_key, content, content_type))
                raise TimeoutError("Azure response lost after accept")

        class _DeletingStore:
            deleted = []

            def __init__(self, config=None):
                self.config = config

            def delete(self, blob_key):
                self.deleted.append(blob_key)

        with self.Session() as db:
            row = db.query(ExternalAttachmentRecord).one()
            row.attempts = 4
            db.commit()
            with (
                patch.dict(os.environ, _STORAGE_ENV),
                patch.object(sync, "AzureBlobAttachmentStore", _TimeoutAfterAcceptStore),
            ):
                self.assertEqual(
                    sync._sync_freshservice_attachment_backlog(
                        db, adapter=_Adapter(), binding_id="legacy", limit=1,
                    ),
                    (0, 1),
                )

        with self.Session() as verify_db:
            row = verify_db.query(ExternalAttachmentRecord).one()
            task = verify_db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(row.storage_status, "error")
            self.assertEqual(row.attempts, 5)
            self.assertNotEqual(row.copy_upload_blob_key, row.blob_key)
            self.assertEqual(task.blob_key, row.copy_upload_blob_key)
            self.assertEqual(task.status, "pending")

        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "SessionLocal", self.Session),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            self.assertEqual(
                attachment_gc.collect_superseded_attachment_blobs(limit=1),
                {"deleted": 0, "failed": 0, "cancelled": 0, "deferred": 1},
            )

        with self.Session() as db:
            row = db.query(ExternalAttachmentRecord).one()
            task = db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(task.status, "pending")
            row.storage_status = "superseded"
            row.source_url = None
            sync._clear_copy_upload_provenance(row)
            task.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "SessionLocal", self.Session),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            self.assertEqual(
                attachment_gc.collect_superseded_attachment_blobs(limit=1),
                {"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0},
            )

        with self.Session() as verify_db:
            task = verify_db.query(AttachmentBlobDeletionRecord).one()
            self.assertEqual(task.status, "deleted")
            self.assertEqual(_DeletingStore.deleted, [task.blob_key])

    def test_backlog_commits_row_claim_before_download_and_blocks_nested_sweep(self):
        nested = []

        def try_second_worker():
            with self.Session() as db:
                nested.append(sync._sync_freshservice_attachment_backlog(
                    db,
                    adapter=_Adapter(),
                    binding_id="legacy",
                    limit=1,
                ))

        adapter = _Adapter(before_download=try_second_worker)
        with (
            self.Session() as db,
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(sync, "AzureBlobAttachmentStore", _Store),
        ):
            result = sync._sync_freshservice_attachment_backlog(
                db, adapter=adapter, binding_id="legacy", limit=1
            )

        self.assertEqual(result, (1, 0))
        self.assertEqual(nested, [(0, 0)])
        self.assertEqual(adapter.downloads, ["https://example.freshservice.com/attachments/91"])
        self.assertEqual(len(_Store.uploads), 1)
        self.assertEqual(
            _Store.configs[0].account_identity,
            "v2:tickety@tickety.blob.core.windows.net",
        )

    def test_backlog_upload_uses_the_provenance_snapshot_passed_to_store(self):
        storage_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.core.windows.net",
            container="tickety-attachments",
            connection_string=None,
        )
        with (
            self.Session() as db,
            patch.object(
                sync, "attachment_storage_config", return_value=storage_config,
            ) as config_loader,
            patch.object(sync, "AzureBlobAttachmentStore", _Store),
        ):
            result = sync._sync_freshservice_attachment_backlog(
                db, adapter=_Adapter(), binding_id="legacy", limit=1,
            )

        self.assertEqual(result, (1, 0))
        config_loader.assert_called_once_with()
        self.assertEqual(len(_Store.configs), 1)
        self.assertIs(_Store.configs[0], storage_config)


class AttachmentCopyLeaseMigrationTests(unittest.TestCase):
    def test_migration_adds_adoptable_copy_lease_columns_and_ready_index(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{Path(directory) / 'copy-lease.db'}"
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", url)
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                command.upgrade(config, "0051")
                command.upgrade(config, "head")
                engine = create_engine(url)
                try:
                    inspector = inspect(engine)
                    columns = {
                        column["name"]
                        for column in inspector.get_columns("external_attachments")
                    }
                    self.assertTrue({
                        "copy_lease_token", "copy_lease_expires_at",
                        "copy_upload_blob_key", "copy_upload_storage_provider",
                        "copy_upload_storage_account_identity",
                        "copy_upload_storage_container", "copy_upload_started_at",
                    }.issubset(columns))
                    indexes = {
                        index["name"]: index["column_names"]
                        for index in inspector.get_indexes("external_attachments")
                    }
                    self.assertEqual(indexes["ix_external_attachments_copy_ready"], [
                        "binding_id", "provider", "storage_status", "next_attempt_at",
                        "copy_lease_expires_at", "created_at", "id",
                    ])
                finally:
                    engine.dispose()


if __name__ == "__main__":
    unittest.main()
