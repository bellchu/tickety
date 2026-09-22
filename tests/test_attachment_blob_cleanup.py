import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend import attachment_gc
from app.backend.attachment_storage import AttachmentStorageConfig
from app.backend.database import (
    AttachmentBlobDeletionRecord,
    Base,
    ExternalAttachmentRecord,
    TicketRecord,
)


_STORAGE_ENV = {
    "ATTACHMENT_STORAGE_PROVIDER": "azure_blob",
    "AZURE_STORAGE_ACCOUNT_URL": "https://tickety.blob.core.windows.net",
    "AZURE_STORAGE_CONTAINER": "tickety-attachments",
}


class _DeletingStore:
    deleted = []
    observe = None

    def __init__(self, config=None):
        self.config = config

    def delete(self, blob_key):
        if self.observe is not None:
            self.observe()
        self.deleted.append(blob_key)


class _FailingStore:
    def __init__(self, config=None):
        self.config = config

    def delete(self, _blob_key):
        raise RuntimeError("Azure unavailable")


class AttachmentBlobCleanupTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(TicketRecord(
            id="attachment-gc-ticket",
            binding_id="legacy",
            external_source="freshservice",
            external_id="4001",
            subject="Attachment cleanup",
            description="private attachment cleanup test",
            reporter="requester@example.test",
            status="Open",
            workflow_status="Open",
            priority="P3",
            created_at=datetime.utcnow(),
        ))
        self.db.commit()
        self.session_patch = patch.object(attachment_gc, "SessionLocal", self.Session)
        self.session_patch.start()
        _DeletingStore.deleted = []
        _DeletingStore.observe = None

    def tearDown(self):
        self.session_patch.stop()
        self.db.close()
        self.engine.dispose()

    def _retired_attachment(self, *, blob_key="bindings/legacy/old.png"):
        row = ExternalAttachmentRecord(
            id="attachment-gc-row",
            binding_id="legacy",
            provider="freshservice",
            ticket_id="attachment-gc-ticket",
            provider_ticket_id="4001",
            owner_type="ticket",
            owner_external_id="4001",
            external_id="old-attachment",
            file_name="old.png",
            blob_key=blob_key,
            storage_status="superseded",
            stored_at=datetime.utcnow() - timedelta(days=1),
            storage_provider="azure_blob",
            storage_account_identity="v2:tickety@tickety.blob.core.windows.net",
            storage_container="tickety-attachments",
        )
        self.db.add(row)
        self.assertTrue(attachment_gc.enqueue_attachment_blob_deletion(self.db, row))
        self.db.commit()
        return row

    def test_deletion_is_durable_before_remote_call_and_is_bounded(self):
        self._retired_attachment()
        observed_statuses = []

        def observe():
            other = self.Session()
            try:
                observed_statuses.append(other.query(AttachmentBlobDeletionRecord.status).one()[0])
            finally:
                other.close()

        _DeletingStore.observe = staticmethod(observe)
        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        task = self.db.query(AttachmentBlobDeletionRecord).one()
        self.assertEqual(result, {"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0})
        self.assertEqual(_DeletingStore.deleted, ["bindings/legacy/old.png"])
        self.assertEqual(observed_statuses, ["processing"])
        self.assertEqual(task.status, "deleted")
        self.assertIsNotNone(task.completed_at)
        self.assertIsNone(task.lease_token)

    def test_gc_delete_uses_the_same_snapshot_that_validated_the_target(self):
        self._retired_attachment()
        storage_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.core.windows.net",
            container="tickety-attachments",
            connection_string=None,
        )
        store_configs = []

        class _SnapshotStore:
            def __init__(self, config=None):
                store_configs.append(config)

            def delete(self, _blob_key):
                return None

        with (
            patch.object(
                attachment_gc,
                "attachment_storage_config",
                return_value=storage_config,
            ) as config_loader,
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _SnapshotStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        self.assertEqual(result, {"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0})
        config_loader.assert_called_once_with()
        self.assertEqual(len(store_configs), 1)
        self.assertIs(store_configs[0], storage_config)

    def test_target_configuration_mismatch_defers_without_deleting(self):
        self._retired_attachment()
        changed_target = dict(_STORAGE_ENV, AZURE_STORAGE_ACCOUNT_URL="https://other.blob.core.windows.net")
        with (
            patch.dict(os.environ, changed_target),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        task = self.db.query(AttachmentBlobDeletionRecord).one()
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(_DeletingStore.deleted, [])
        self.assertEqual(task.status, "pending")
        self.assertIn("storage_target_unavailable", task.last_error)
        self.assertIsNotNone(task.next_attempt_at)
        self.assertEqual(task.attempts, 0)

    def test_restored_storage_target_can_delete_after_repeated_deferrals(self):
        self._retired_attachment()
        changed_target = dict(
            _STORAGE_ENV,
            AZURE_STORAGE_ACCOUNT_URL="https://other.blob.core.windows.net",
        )
        with (
            patch.dict(os.environ, changed_target),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            # More deferrals than the finite remote deletion budget must not
            # mark the task terminal: no remote delete was attempted.
            for _ in range(8):
                result = attachment_gc.collect_superseded_attachment_blobs(limit=1)
                self.assertEqual(result["deferred"], 1)
                self.db.expire_all()
                task = self.db.query(AttachmentBlobDeletionRecord).one()
                self.assertEqual(task.status, "pending")
                self.assertEqual(task.attempts, 0)
                task.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
                self.db.commit()

        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        self.db.expire_all()
        task = self.db.query(AttachmentBlobDeletionRecord).one()
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(task.status, "deleted")
        self.assertEqual(_DeletingStore.deleted, ["bindings/legacy/old.png"])

    def test_reactivated_attachment_deletes_unreferenced_old_key(self):
        row = self._retired_attachment()
        row.storage_status = "pending"
        row.blob_key = "bindings/legacy/newly-revived.png"
        self.db.commit()
        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        task = self.db.query(AttachmentBlobDeletionRecord).one()
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(_DeletingStore.deleted, ["bindings/legacy/old.png"])
        self.assertEqual(task.status, "deleted")

    def test_legacy_colliding_live_key_defers_deletion(self):
        """A historical truncated key must not delete another live blob."""
        shared_key = "bindings/legacy/historical-collision.png"
        self._retired_attachment(blob_key=shared_key)
        self.db.add(ExternalAttachmentRecord(
            id="attachment-gc-live-collision",
            binding_id="legacy",
            provider="freshservice",
            ticket_id="attachment-gc-ticket",
            provider_ticket_id="4001",
            owner_type="ticket",
            owner_external_id="4001",
            external_id="still-live-attachment",
            file_name="still-live.png",
            blob_key=shared_key,
            storage_status="stored",
            stored_at=datetime.utcnow(),
            storage_provider="azure_blob",
            storage_account_identity="v2:tickety@tickety.blob.core.windows.net",
            storage_container="tickety-attachments",
        ))
        self.db.commit()

        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        self.db.expire_all()
        task = self.db.query(AttachmentBlobDeletionRecord).one()
        self.assertEqual(result, {"deleted": 0, "failed": 0, "cancelled": 0, "deferred": 1})
        self.assertEqual(_DeletingStore.deleted, [])
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.attempts, 0)
        self.assertIn("blob_key_still_referenced", task.last_error)

    def test_same_legacy_key_on_a_different_target_does_not_block_cleanup(self):
        """Target-bound tasks do not retain unrelated accounts forever."""
        shared_key = "bindings/legacy/cross-account-key.png"
        self._retired_attachment(blob_key=shared_key)
        self.db.add(ExternalAttachmentRecord(
            id="attachment-gc-foreign-target",
            binding_id="legacy",
            provider="freshservice",
            ticket_id="attachment-gc-ticket",
            provider_ticket_id="4001",
            owner_type="ticket",
            owner_external_id="4001",
            external_id="foreign-target-attachment",
            file_name="foreign.png",
            blob_key=shared_key,
            storage_status="stored",
            stored_at=datetime.utcnow(),
            storage_provider="azure_blob",
            storage_account_identity="other-account",
            storage_container="other-container",
        ))
        self.db.commit()

        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _DeletingStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        task = self.db.query(AttachmentBlobDeletionRecord).one()
        self.assertEqual(result, {"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0})
        self.assertEqual(_DeletingStore.deleted, [shared_key])
        self.assertEqual(task.status, "deleted")

    def test_remote_failure_is_durable_retry_not_open_transaction(self):
        self._retired_attachment()
        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _FailingStore),
        ):
            result = attachment_gc.collect_superseded_attachment_blobs(limit=1)

        task = self.db.query(AttachmentBlobDeletionRecord).one()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.attempts, 1)
        self.assertIsNotNone(task.next_attempt_at)
        self.assertIn("RuntimeError", task.last_error)

    def test_missing_late_copy_candidates_yield_to_retirements_and_rotate(self):
        """Perpetual 404 safety must not starve ordinary blob retirement."""
        now = datetime.utcnow()
        target = {
            "storage_provider": "azure_blob",
            "storage_account_identity": "v2:tickety@tickety.blob.core.windows.net",
            "storage_container": "tickety-attachments",
        }

        def add_retired(identifier, blob_key, *, requested_at, waiting=False):
            attachment = ExternalAttachmentRecord(
                id=f"attachment-gc-{identifier}",
                binding_id="legacy",
                provider="freshservice",
                ticket_id="attachment-gc-ticket",
                provider_ticket_id="4001",
                owner_type="ticket",
                owner_external_id="4001",
                external_id=identifier,
                file_name=f"{identifier}.png",
                blob_key=blob_key,
                storage_status="superseded",
                stored_at=now,
                **target,
            )
            task = AttachmentBlobDeletionRecord(
                id=f"task-gc-{identifier}",
                attachment_id=attachment.id,
                blob_key=blob_key,
                requested_at=requested_at,
                next_attempt_at=now - timedelta(seconds=1),
                status="pending",
                **target,
            )
            if waiting:
                task.last_error = attachment_gc._safe_error(RuntimeError(
                    attachment_gc._LATE_COPY_WAITING_MARKER
                ))
            self.db.add_all((attachment, task))
            return task

        first_missing = add_retired(
            "missing-first",
            "bindings/legacy/old.copy-00000000-0000-4000-8000-000000000001",
            requested_at=now - timedelta(minutes=3),
            waiting=True,
        )
        second_missing = add_retired(
            "missing-second",
            "bindings/legacy/old.copy-00000000-0000-4000-8000-000000000002",
            requested_at=now - timedelta(minutes=2),
            waiting=True,
        )
        ordinary = add_retired(
            "ordinary",
            "bindings/legacy/ordinary.png",
            requested_at=now - timedelta(minutes=1),
        )
        self.db.commit()

        class _PresenceStore:
            delete_calls = []

            def __init__(self, config=None):
                self.config = config

            def delete(self, blob_key):
                self.delete_calls.append(blob_key)
                return not attachment_gc._is_copy_attempt_blob_key(blob_key)

        with (
            patch.dict(os.environ, _STORAGE_ENV),
            patch.object(attachment_gc, "AzureBlobAttachmentStore", _PresenceStore),
        ):
            # Even though both missing candidates are older, the ordinary
            # retirement gets the next bounded cleanup slot.
            self.assertEqual(
                attachment_gc.collect_superseded_attachment_blobs(limit=1),
                {"deleted": 1, "failed": 0, "cancelled": 0, "deferred": 0},
            )
            # With no ordinary task ready, the two due missing candidates take
            # turns: the first reschedules before the second is claimed.
            self.assertEqual(
                attachment_gc.collect_superseded_attachment_blobs(limit=1),
                {"deleted": 0, "failed": 0, "cancelled": 0, "deferred": 1},
            )
            self.assertEqual(
                attachment_gc.collect_superseded_attachment_blobs(limit=1),
                {"deleted": 0, "failed": 0, "cancelled": 0, "deferred": 1},
            )

        self.db.expire_all()
        self.assertEqual(ordinary.status, "deleted")
        self.assertEqual(first_missing.status, "pending")
        self.assertEqual(second_missing.status, "pending")
        self.assertGreater(first_missing.next_attempt_at, now)
        self.assertGreater(second_missing.next_attempt_at, now)
        self.assertEqual(
            _PresenceStore.delete_calls,
            [ordinary.blob_key, first_missing.blob_key, second_missing.blob_key],
        )

    def test_unproven_legacy_target_never_enqueues_deletion(self):
        row = ExternalAttachmentRecord(
            id="attachment-gc-legacy",
            binding_id="legacy",
            provider="freshservice",
            ticket_id="attachment-gc-ticket",
            provider_ticket_id="4001",
            owner_type="ticket",
            owner_external_id="4001",
            external_id="legacy-attachment",
            file_name="legacy.png",
            blob_key="bindings/legacy/legacy.png",
            storage_status="superseded",
            stored_at=datetime.utcnow(),
        )
        self.db.add(row)
        self.assertFalse(attachment_gc.enqueue_attachment_blob_deletion(self.db, row))
        self.db.commit()
        self.assertEqual(self.db.query(AttachmentBlobDeletionRecord).count(), 0)

    def test_deletion_identity_includes_storage_target_but_same_target_is_idempotent(self):
        row = self._retired_attachment(blob_key="bindings/legacy/target-bound.png")
        self.assertFalse(attachment_gc.enqueue_attachment_blob_deletion(self.db, row))

        row.storage_account_identity = "other-account"
        row.storage_container = "other-container"
        self.assertTrue(attachment_gc.enqueue_attachment_blob_deletion(self.db, row))
        self.assertFalse(attachment_gc.enqueue_attachment_blob_deletion(self.db, row))
        self.db.commit()

        tasks = self.db.query(AttachmentBlobDeletionRecord).order_by(
            AttachmentBlobDeletionRecord.storage_account_identity
        ).all()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(
            {
                (task.storage_account_identity, task.storage_container)
                for task in tasks
            },
            {
                ("v2:tickety@tickety.blob.core.windows.net", "tickety-attachments"),
                ("other-account", "other-container"),
            },
        )

    def test_duplicate_enqueue_race_preserves_the_outer_sync_transaction(self):
        """A concurrent durable intent must not roll back attachment retirement.

        The contender commits exactly after the caller has chosen to enqueue
        but before its savepoint flushes.  This models two sync replicas
        converging on the same retired attachment without depending on a
        process-local read-before-write check.
        """
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{os.path.join(directory, 'race.db')}")
            sessions = sessionmaker(bind=engine)
            Base.metadata.create_all(engine)
            attachment_id = "attachment-gc-race"
            blob_key = "bindings/legacy/race.png"
            try:
                with sessions() as setup:
                    setup.add(TicketRecord(
                        id="attachment-gc-race-ticket",
                        binding_id="legacy",
                        external_source="freshservice",
                        external_id="4002",
                        subject="Attachment cleanup race",
                        description="private attachment cleanup race test",
                        reporter="requester@example.test",
                        status="Open",
                        workflow_status="Open",
                        priority="P3",
                        created_at=datetime.utcnow(),
                    ))
                    setup.add(ExternalAttachmentRecord(
                        id=attachment_id,
                        binding_id="legacy",
                        provider="freshservice",
                        ticket_id="attachment-gc-race-ticket",
                        provider_ticket_id="4002",
                        owner_type="ticket",
                        owner_external_id="4002",
                        external_id="race-attachment",
                        file_name="race.png",
                        blob_key=blob_key,
                        storage_status="superseded",
                        stored_at=datetime.utcnow(),
                        storage_provider="azure_blob",
                        storage_account_identity="v2:tickety@tickety.blob.core.windows.net",
                        storage_container="tickety-attachments",
                    ))
                    setup.commit()

                def insert_contender():
                    with sessions() as contender:
                        contender.add(AttachmentBlobDeletionRecord(
                            id="contending-deletion-task",
                            attachment_id=attachment_id,
                            blob_key=blob_key,
                            storage_provider="azure_blob",
                            storage_account_identity="v2:tickety@tickety.blob.core.windows.net",
                            storage_container="tickety-attachments",
                            status="pending",
                            attempts=0,
                        ))
                        contender.commit()

                class RacingSession(Session):
                    def __init__(self, *args, inject_contender, **kwargs):
                        super().__init__(*args, **kwargs)
                        self._inject_contender = inject_contender
                        self._injected = False

                    def begin_nested(self):
                        if not self._injected:
                            self._injected = True
                            self._inject_contender()
                        return super().begin_nested()

                racing_sessions = sessionmaker(
                    bind=engine,
                    class_=RacingSession,
                    inject_contender=insert_contender,
                )
                detached_retirement = ExternalAttachmentRecord(
                    id=attachment_id,
                    blob_key=blob_key,
                    storage_status="superseded",
                    stored_at=datetime.utcnow(),
                    storage_provider="azure_blob",
                    storage_account_identity="v2:tickety@tickety.blob.core.windows.net",
                    storage_container="tickety-attachments",
                )
                with racing_sessions() as caller:
                    self.assertFalse(
                        attachment_gc.enqueue_attachment_blob_deletion(
                            caller, detached_retirement
                        )
                    )
                    self.assertTrue(caller.in_transaction())
                    caller.execute(text(
                        "UPDATE external_attachments SET file_name = 'race-preserved.png' "
                        "WHERE id = 'attachment-gc-race'"
                    ))
                    caller.commit()

                with sessions() as verify:
                    self.assertEqual(
                        verify.query(AttachmentBlobDeletionRecord).count(), 1
                    )
                    self.assertEqual(
                        verify.execute(text(
                            "SELECT file_name FROM external_attachments "
                            "WHERE id = 'attachment-gc-race'"
                        )).scalar_one(),
                        "race-preserved.png",
                    )
            finally:
                engine.dispose()

    def test_account_identity_matches_url_and_connection_string_auth_modes(self):
        from app.backend.attachment_storage import (
            AttachmentStorageConfig,
            attachment_storage_target_matches,
        )

        url_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.core.windows.net",
            container="tickety-attachments",
            connection_string=None,
        )
        connection_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="",
            container="tickety-attachments",
            connection_string="DefaultEndpointsProtocol=https;AccountName=tickety;AccountKey=not-used-here",
        )
        expected_identity = "v2:tickety@tickety.blob.core.windows.net"
        self.assertEqual(url_config.account_identity, expected_identity)
        self.assertEqual(connection_config.account_identity, expected_identity)
        self.assertTrue(attachment_storage_target_matches(
            storage_provider="azure_blob",
            storage_account_identity=expected_identity,
            storage_container="tickety-attachments",
            config=connection_config,
        ))

    def test_target_identity_binds_same_account_and_container_to_endpoint_authority(self):
        from app.backend.attachment_storage import (
            AttachmentStorageConfig,
            attachment_storage_target_matches,
        )

        primary = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.private.example.test",
            container="tickety-attachments",
            connection_string=None,
        )
        replacement = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="https://tickety.blob.secondary.example.test",
            container="tickety-attachments",
            connection_string=None,
        )

        self.assertEqual(
            primary.account_identity,
            "v2:tickety@tickety.blob.private.example.test",
        )
        self.assertNotEqual(primary.account_identity, replacement.account_identity)
        self.assertFalse(attachment_storage_target_matches(
            storage_provider="azure_blob",
            storage_account_identity=primary.account_identity,
            storage_container="tickety-attachments",
            config=replacement,
        ))
        # The old AccountName-only provenance is ambiguous across authorities
        # and must not be promoted to the active target during an upgrade.
        self.assertFalse(attachment_storage_target_matches(
            storage_provider="azure_blob",
            storage_account_identity="tickety",
            storage_container="tickety-attachments",
            config=primary,
        ))

    def test_target_identity_canonicalizes_endpoint_suffix_without_secrets(self):
        from app.backend.attachment_storage import (
            AttachmentStorageConfig,
            AttachmentStorageError,
            AzureBlobAttachmentStore,
        )

        config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="",
            container="tickety-attachments",
            connection_string=(
                "DefaultEndpointsProtocol=https;AccountName=tickety;"
                "AccountKey=must-not-be-persisted;EndpointSuffix=private.example.test"
            ),
        )
        self.assertEqual(
            config.account_identity,
            "v2:tickety@tickety.blob.private.example.test",
        )
        self.assertNotIn("must-not-be-persisted", config.account_identity)

        blob_endpoint_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="",
            container="tickety-attachments",
            connection_string=(
                "DefaultEndpointsProtocol=https;AccountName=tickety;"
                "AccountKey=must-not-be-persisted;"
                "BlobEndpoint=https://tickety.blob.secondary.example.test/"
            ),
        )
        self.assertEqual(
            blob_endpoint_config.account_identity,
            "v2:tickety@tickety.blob.secondary.example.test",
        )
        self.assertNotEqual(config.account_identity, blob_endpoint_config.account_identity)

        insecure_legacy_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="",
            container="tickety-attachments",
            connection_string="DefaultEndpointsProtocol=http;AccountName=tickety;AccountKey=unused",
        )
        self.assertEqual(insecure_legacy_config.account_identity, "")
        with self.assertRaisesRegex(
            AttachmentStorageError, "connection_string_endpoint_invalid"
        ):
            AzureBlobAttachmentStore(insecure_legacy_config)

        insecure_blob_endpoint_config = AttachmentStorageConfig(
            provider="azure_blob",
            account_url="",
            container="tickety-attachments",
            connection_string=(
                "AccountName=tickety;AccountKey=unused;"
                "BlobEndpoint=http://tickety.blob.private.example.test"
            ),
        )
        self.assertEqual(insecure_blob_endpoint_config.account_identity, "")
        with self.assertRaisesRegex(
            AttachmentStorageError, "connection_string_endpoint_invalid"
        ):
            AzureBlobAttachmentStore(insecure_blob_endpoint_config)
