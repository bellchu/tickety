"""Bounded, durable garbage collection for retired private attachment blobs."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .attachment_storage import (
    AzureBlobAttachmentStore,
    attachment_storage_config,
    attachment_storage_target_matches,
)
from .database import AttachmentBlobDeletionRecord, ExternalAttachmentRecord, SessionLocal


_LEASE_SECONDS = 5 * 60
_MAX_ATTEMPTS = 8
_LATE_COPY_WAITING_MARKER = "attachment_blob_delete_waiting_for_late_copy"


def _is_copy_attempt_blob_key(blob_key: str) -> bool:
    """Recognize the immutable target format used by fenced copy attempts."""
    prefix, separator, token = (blob_key or "").rpartition(".copy-")
    if not prefix or not separator:
        return False
    try:
        return str(uuid.UUID(token)) == token
    except (TypeError, ValueError, AttributeError):
        return False


def attachment_blob_deletions_per_sweep() -> int:
    """Keep a remote destructive sweep deliberately small and configurable."""
    try:
        configured = int(os.getenv("ATTACHMENT_BLOB_DELETIONS_PER_SYNC", "2"))
    except (TypeError, ValueError):
        configured = 2
    return max(0, min(configured, 20))


def enqueue_attachment_blob_deletion(
    db: Session,
    attachment: ExternalAttachmentRecord,
) -> bool:
    """Record deletion intent after a stored blob has been durably retired.

    The caller must set ``storage_status='superseded'`` in the same database
    transaction.  Old rows that predate target provenance are intentionally
    retained: guessing a new storage account would be destructive.
    """
    if (
        attachment.storage_status != "superseded"
        or not attachment.blob_key
        or not attachment.stored_at
        or not attachment.storage_provider
        or not attachment.storage_account_identity
        or not attachment.storage_container
    ):
        return False
    return enqueue_retired_attachment_blob_deletion(
        db,
        attachment_id=attachment.id,
        blob_key=attachment.blob_key,
        storage_provider=attachment.storage_provider,
        storage_account_identity=attachment.storage_account_identity,
        storage_container=attachment.storage_container,
    )


def enqueue_retired_attachment_blob_deletion(
    db: Session,
    *,
    attachment_id: str,
    blob_key: str,
    storage_provider: str,
    storage_account_identity: str,
    storage_container: str,
) -> bool:
    """Persist one immutable, target-bound remote deletion intent.

    A late copy result can have uploaded an old immutable key after the row
    was resurrected with a new key.  That result has no current row state from
    which ``enqueue_attachment_blob_deletion`` can infer the old target, so it
    must pass the target that received its upload explicitly.  Callers may use
    this only after the remote object is known to exist or may have been
    accepted by the storage service. In the latter case the collector's live
    ownership check must keep the intent deferred until retirement is proven.
    """
    if not all((
        attachment_id,
        blob_key,
        storage_provider,
        storage_account_identity,
        storage_container,
    )):
        return False
    task = AttachmentBlobDeletionRecord(
        id=str(uuid.uuid4()),
        attachment_id=attachment_id,
        blob_key=blob_key,
        storage_provider=storage_provider,
        storage_account_identity=storage_account_identity,
        storage_container=storage_container,
        status="pending",
        attempts=0,
    )
    # A read-before-write check cannot make this idempotent across sync
    # replicas.  Flush only this insert in a savepoint so a competing task
    # which committed after the caller retired its attachment is treated as
    # the same durable intent, not as a reason to roll back the caller's
    # attachment/sync transaction.
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
    except IntegrityError:
        # SQLAlchemy normally expunges objects created in a rolled-back nested
        # transaction.  Be explicit so a dialect/session implementation cannot
        # retry this duplicate when the caller commits its outer transaction.
        if task in db:
            db.expunge(task)
        return False
    return True


def _safe_error(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    parts = ["attachment_blob_delete_failed", type(exc).__name__]
    safe_detail = "".join(
        char for char in str(exc)
        if char.isalnum() or char in ("_", "-")
    )[:96]
    if safe_detail:
        parts.append(safe_detail)
    if status_code is not None:
        parts.append(f"http_{status_code}")
    return ":".join(parts)[:255]


def _storage_matches(task: AttachmentBlobDeletionRecord, storage_config) -> bool:
    return attachment_storage_target_matches(
        storage_provider=task.storage_provider,
        storage_account_identity=task.storage_account_identity,
        storage_container=task.storage_container,
        config=storage_config,
    )


def _claim_next_task(db: Session, now: datetime) -> tuple[str, str] | None:
    """Claim fairly: ready retirements precede absent late-copy candidates."""
    # A candidate that was missing in Azure must remain retryable forever: an
    # already-dispatched fenced upload can still arrive after a 404.  Those
    # tasks must not, however, monopolize a bounded sweep merely because they
    # were requested first.  Within each class, due time gives waiting
    # candidates a round-robin order after each 60-second reschedule.
    waiting_late_copy = AttachmentBlobDeletionRecord.last_error.contains(
        _LATE_COPY_WAITING_MARKER
    )
    candidate = db.query(AttachmentBlobDeletionRecord.id).filter(
        or_(
            and_(
                AttachmentBlobDeletionRecord.status == "pending",
                or_(
                    AttachmentBlobDeletionRecord.next_attempt_at.is_(None),
                    AttachmentBlobDeletionRecord.next_attempt_at <= now,
                ),
            ),
            and_(
                AttachmentBlobDeletionRecord.status == "processing",
                AttachmentBlobDeletionRecord.lease_expires_at.isnot(None),
                AttachmentBlobDeletionRecord.lease_expires_at <= now,
            ),
        ),
    ).order_by(
        case((waiting_late_copy, 1), else_=0).asc(),
        func.coalesce(
            AttachmentBlobDeletionRecord.next_attempt_at,
            AttachmentBlobDeletionRecord.requested_at,
        ).asc(),
        AttachmentBlobDeletionRecord.requested_at.asc(),
        AttachmentBlobDeletionRecord.id.asc(),
    ).first()
    if candidate is None:
        return None
    task_id = candidate[0]
    token = str(uuid.uuid4())
    updated = db.query(AttachmentBlobDeletionRecord).filter(
        AttachmentBlobDeletionRecord.id == task_id,
        or_(
            and_(
                AttachmentBlobDeletionRecord.status == "pending",
                or_(
                    AttachmentBlobDeletionRecord.next_attempt_at.is_(None),
                    AttachmentBlobDeletionRecord.next_attempt_at <= now,
                ),
            ),
            and_(
                AttachmentBlobDeletionRecord.status == "processing",
                AttachmentBlobDeletionRecord.lease_expires_at.isnot(None),
                AttachmentBlobDeletionRecord.lease_expires_at <= now,
            ),
        ),
    ).update({
        AttachmentBlobDeletionRecord.status: "processing",
        AttachmentBlobDeletionRecord.lease_token: token,
        AttachmentBlobDeletionRecord.lease_expires_at: now + timedelta(seconds=_LEASE_SECONDS),
        AttachmentBlobDeletionRecord.attempts: AttachmentBlobDeletionRecord.attempts + 1,
        AttachmentBlobDeletionRecord.last_error: None,
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return None
    db.commit()
    return task_id, token


def _live_attachment_may_share_task_target(
    task: AttachmentBlobDeletionRecord,
):
    """Build the conservative target predicate for historical shared keys."""
    target_unknown = or_(
        ExternalAttachmentRecord.storage_provider.is_(None),
        ExternalAttachmentRecord.storage_provider == "",
        ExternalAttachmentRecord.storage_account_identity.is_(None),
        ExternalAttachmentRecord.storage_account_identity == "",
        ExternalAttachmentRecord.storage_container.is_(None),
        ExternalAttachmentRecord.storage_container == "",
    )
    same_target = and_(
        ExternalAttachmentRecord.storage_provider == task.storage_provider,
        ExternalAttachmentRecord.storage_account_identity == task.storage_account_identity,
        ExternalAttachmentRecord.storage_container == task.storage_container,
    )
    return or_(target_unknown, same_target)


def _validate_retired_blob_ownership(
    db: Session, task_id: str, token: str, now: datetime,
) -> tuple[str, AttachmentBlobDeletionRecord | None]:
    """Prove that a claimed key has no live owner before remote deletion.

    A task remains a valid retirement record when its original row moves to a
    new immutable key during resurrection.  Conversely, a non-superseded row
    on the task's key reverses *that* retirement.  Historical truncated keys
    can collide, so every other live row bound to the same (or unproven)
    target fences remote deletion until ownership is unambiguous.
    """
    task = db.query(AttachmentBlobDeletionRecord).filter(
        AttachmentBlobDeletionRecord.id == task_id,
        AttachmentBlobDeletionRecord.status == "processing",
        AttachmentBlobDeletionRecord.lease_token == token,
        AttachmentBlobDeletionRecord.lease_expires_at > now,
    ).with_for_update().first()
    if task is None:
        db.rollback()
        return "lost", None
    attachment = db.query(ExternalAttachmentRecord).filter(
        ExternalAttachmentRecord.id == task.attachment_id,
    ).with_for_update().first()
    if attachment is None:
        task.status = "cancelled"
        task.completed_at = now
        task.lease_token = None
        task.lease_expires_at = None
        task.last_error = "attachment_blob_delete_cancelled:retirement_reversed"
        db.commit()
        return "cancelled", None

    pending_upload_matches_task = bool(
        attachment.copy_upload_started_at
        and attachment.copy_upload_blob_key == task.blob_key
        and attachment.copy_upload_storage_provider == task.storage_provider
        and (
            attachment.copy_upload_storage_account_identity
            == task.storage_account_identity
        )
        and attachment.copy_upload_storage_container == task.storage_container
    )
    if pending_upload_matches_task:
        # A timeout or commit loss can follow an Azure-accepted upload.  The
        # candidate object is token-derived and therefore intentionally need
        # not equal the row's logical/final key; matching the provenance, not
        # that mutable pointer, is what proves it may still be in flight.
        # Retain its task without remote I/O until the metadata retires or
        # replaces this candidate.
        task.status = "pending"
        task.lease_token = None
        task.lease_expires_at = None
        task.attempts = max(0, int(task.attempts or 0) - 1)
        task.next_attempt_at = now + timedelta(seconds=60)
        task.last_error = (
            "attachment_blob_delete_deferred:upload_result_ambiguous"
        )
        db.commit()
        return "deferred", None
    if (
        attachment.blob_key == task.blob_key
        and attachment.storage_status != "superseded"
    ):
        task.status = "cancelled"
        task.completed_at = now
        task.lease_token = None
        task.lease_expires_at = None
        task.last_error = "attachment_blob_delete_cancelled:retirement_reversed"
        db.commit()
        return "cancelled", None

    live_reference = db.query(ExternalAttachmentRecord.id).filter(
        ExternalAttachmentRecord.id != task.attachment_id,
        ExternalAttachmentRecord.blob_key == task.blob_key,
        ExternalAttachmentRecord.storage_status != "superseded",
        _live_attachment_may_share_task_target(task),
    ).with_for_update().first()
    if live_reference is not None:
        # This is not a remote failure: the old key is still reachable through
        # a live historical row.  Give the task back without consuming its
        # finite I/O budget, so a later metadata retirement can make it safe.
        task.status = "pending"
        task.lease_token = None
        task.lease_expires_at = None
        task.attempts = max(0, int(task.attempts or 0) - 1)
        task.next_attempt_at = now + timedelta(seconds=60)
        task.last_error = (
            "attachment_blob_delete_deferred:blob_key_still_referenced"
        )
        db.commit()
        return "deferred", None
    db.commit()
    return "ready", task


def _record_delete_success(db: Session, task_id: str, token: str, now: datetime) -> bool:
    updated = db.query(AttachmentBlobDeletionRecord).filter(
        AttachmentBlobDeletionRecord.id == task_id,
        AttachmentBlobDeletionRecord.status == "processing",
        AttachmentBlobDeletionRecord.lease_token == token,
    ).update({
        AttachmentBlobDeletionRecord.status: "deleted",
        AttachmentBlobDeletionRecord.completed_at: now,
        AttachmentBlobDeletionRecord.lease_token: None,
        AttachmentBlobDeletionRecord.lease_expires_at: None,
        AttachmentBlobDeletionRecord.next_attempt_at: None,
        AttachmentBlobDeletionRecord.last_error: None,
    }, synchronize_session=False)
    db.commit()
    return updated == 1


def _record_delete_failure(
    db: Session,
    task_id: str,
    token: str,
    exc: Exception,
    now: datetime,
    *,
    consume_attempt: bool = True,
) -> None:
    task = db.query(AttachmentBlobDeletionRecord).filter(
        AttachmentBlobDeletionRecord.id == task_id,
        AttachmentBlobDeletionRecord.status == "processing",
        AttachmentBlobDeletionRecord.lease_token == token,
    ).with_for_update().first()
    if task is None:
        db.rollback()
        return
    task.lease_token = None
    task.lease_expires_at = None
    task.last_error = _safe_error(exc)
    # Claiming happens before the target comparison to retain a short,
    # durable lease across replicas.  A temporarily different configured
    # account/container has not attempted remote deletion, though, so undo
    # that claim's accounting instead of permanently exhausting the remote-I/O
    # budget while the original target is unavailable.
    if not consume_attempt:
        task.attempts = max(0, int(task.attempts or 0) - 1)
    if consume_attempt and task.attempts >= _MAX_ATTEMPTS:
        task.status = "failed"
        task.next_attempt_at = None
    else:
        task.status = "pending"
        delay = (
            min(6 * 60 * 60, 60 * (2 ** max(0, task.attempts - 1)))
            if consume_attempt
            else 60
        )
        task.next_attempt_at = now + timedelta(seconds=delay)
    db.commit()


def collect_superseded_attachment_blobs(*, limit: int | None = None) -> dict[str, int]:
    """Perform a bounded remote sweep after durable retirement confirmation."""
    limit = attachment_blob_deletions_per_sweep() if limit is None else max(0, limit)
    result = {"deleted": 0, "failed": 0, "cancelled": 0, "deferred": 0}
    # One configuration snapshot binds both target validation and every
    # destructive client in this sweep. A concurrent settings rotation must
    # never redirect a task after its provenance check succeeds.
    storage_config = attachment_storage_config()
    if limit <= 0 or not storage_config.configured:
        return result
    db = SessionLocal()
    try:
        for _ in range(limit):
            now = datetime.utcnow()
            claim = _claim_next_task(db, now)
            if claim is None:
                break
            task_id, token = claim
            ownership, task = _validate_retired_blob_ownership(
                db, task_id, token, now
            )
            if ownership == "cancelled":
                result["cancelled"] += 1
                continue
            if ownership == "deferred":
                result["deferred"] += 1
                continue
            if ownership != "ready" or task is None:
                continue
            if not _storage_matches(task, storage_config):
                # Retain intent but never guess a new container/account.  The
                # task becomes due again if its original target is restored.
                _record_delete_failure(
                    db, task_id, token,
                    RuntimeError("attachment_blob_delete_storage_target_unavailable"),
                    now,
                    consume_attempt=False,
                )
                result["deferred"] += 1
                continue
            try:
                deleted_remote_blob = AzureBlobAttachmentStore(storage_config).delete(
                    task.blob_key
                )
            except Exception as exc:
                _record_delete_failure(db, task_id, token, exc, now)
                result["failed"] += 1
                print(f"[attachments] blob cleanup failed kind={type(exc).__name__}")
                continue
            if deleted_remote_blob is False and _is_copy_attempt_blob_key(task.blob_key):
                # A fenced worker can still receive a delayed Azure success
                # after the collector sees 404.  Do not terminally acknowledge
                # that absence: retain the immutable-target intent until a
                # later sweep has actually observed and removed the object.
                _record_delete_failure(
                    db, task_id, token,
                    RuntimeError(_LATE_COPY_WAITING_MARKER),
                    now,
                    consume_attempt=False,
                )
                result["deferred"] += 1
                continue
            if _record_delete_success(db, task_id, token, datetime.utcnow()):
                result["deleted"] += 1
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
