"""Fail-closed transition controls shared by API and worker processes."""

import hashlib
import hmac

from sqlalchemy.orm import Session

from .database import SessionRecord, TicketRecord, UserRecord


_PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
_SEEDED_DEMO_IDENTITIES = {
    "u-alice": "alice@company.com",
    "u-bob": "bob@company.com",
    "u-carol": "carol@company.com",
}
_SEEDED_DEMO_PASSWORD = "tickety123"


def _seed_password_matches(password_hash: str | None) -> bool:
    if not password_hash:
        return False
    if len(password_hash) == 64 and all(
        char in "0123456789abcdef" for char in password_hash.lower()
    ):
        expected = hashlib.sha256(_SEEDED_DEMO_PASSWORD.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, password_hash)
    try:
        scheme, iterations_raw, salt, expected = password_hash.split("$", 3)
        if scheme != _PASSWORD_HASH_SCHEME:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            _SEEDED_DEMO_PASSWORD.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations_raw),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (TypeError, ValueError):
        return False


def disable_seeded_demo_identities(db: Session) -> int:
    """Invalidate unchanged demo credentials before any production AI work."""
    candidates = db.query(UserRecord).filter(
        UserRecord.id.in_(set(_SEEDED_DEMO_IDENTITIES)),
        UserRecord.is_active.is_(True),
    ).with_for_update().all()
    users = [
        user for user in candidates
        if (user.email or "").strip().lower()
        == _SEEDED_DEMO_IDENTITIES[user.id]
        and _seed_password_matches(user.password_hash)
    ]
    if not users:
        return 0

    user_ids = [user.id for user in users]
    replacement_admins = db.query(UserRecord).filter(
        UserRecord.role == "admin",
        UserRecord.is_active.is_(True),
        UserRecord.id.notin_(user_ids),
    ).count()
    if replacement_admins == 0:
        raise RuntimeError(
            "Production requires an active non-demo administrator before "
            "repository-known demo credentials can be disabled"
        )

    db.query(SessionRecord).filter(SessionRecord.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    for user in users:
        user.is_active = False
        user.password_hash = None
    db.query(TicketRecord).filter(
        TicketRecord.ai_status.in_(["queued", "running"])
    ).update({
        TicketRecord.ai_status: "stale",
        TicketRecord.ai_claim_id: None,
        TicketRecord.ai_lease_expires_at: None,
        TicketRecord.ai_next_attempt_at: None,
        TicketRecord.ai_error: "production_transition_requires_review",
    }, synchronize_session=False)
    db.commit()
    return len(users)
