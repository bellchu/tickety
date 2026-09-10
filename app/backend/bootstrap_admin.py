"""One-time, interactive first-administrator bootstrap for an empty database."""

from __future__ import annotations

import argparse
import getpass
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import directory_service
from .database import SessionLocal, UserRecord
from .email_service import normalize_email_address, normalize_sender_name
from .passwords import hash_password


_BOOTSTRAP_LOCK_NAMESPACE = 0x5449434B
_BOOTSTRAP_LOCK_KEY = 0x41444D49


def bootstrap_admin(
    db: Session,
    *,
    name: str,
    email: str,
    password: str,
) -> UserRecord:
    normalized_name = normalize_sender_name(name)
    normalized_email = normalize_email_address(email)
    if not normalized_name:
        raise ValueError("Administrator name must not be blank")
    if not 12 <= len(password) <= 1_024:
        raise ValueError("Password must contain between 12 and 1024 characters")

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
            {"namespace": _BOOTSTRAP_LOCK_NAMESPACE, "lock_key": _BOOTSTRAP_LOCK_KEY},
        )
    elif dialect == "sqlite" and not db.in_transaction():
        db.execute(text("BEGIN IMMEDIATE"))

    if db.query(UserRecord.id).first() is not None:
        raise RuntimeError("Bootstrap is allowed only when the users table is empty")

    user = UserRecord(
        id=f"u-{uuid.uuid4().hex}",
        name=normalized_name,
        email=normalized_email,
        email_key=normalized_email,
        role="admin",
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    directory_service.ensure_local_person(db, user.id)
    db.commit()
    db.refresh(user)
    return user


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the first administrator in an empty Tickety database."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    db = SessionLocal()
    try:
        user = bootstrap_admin(
            db,
            name=args.name,
            email=args.email,
            password=password,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"Created administrator {user.email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
