#!/usr/bin/env python3
"""Fail a release preflight when persisted sensitive settings are unsafe."""

from __future__ import annotations

from sqlalchemy import inspect

from app.backend.database import SessionLocal, SettingsRecord
from app.backend.settings import (
    _SENSITIVE_KEYS,
    _decrypt_sensitive_setting,
    _settings_encryption_keyring,
    _verify_settings_encryption_fence,
)


def verify_persisted_sensitive_settings() -> None:
    """Strictly authenticate the keyring and every persisted sensitive row.

    This is intentionally not the runtime hydration reader: runtime hydration
    tolerates an unavailable settings table for compatibility, while a release
    gate must never treat an absent keyring, query failure, or legacy row as a
    clean migration state. A missing settings table is allowed only on an
    entirely empty database so Alembic can create Tickety's first table.
    """
    active_kid, _keyring = _settings_encryption_keyring()
    db = SessionLocal()
    try:
        table_names = set(inspect(db.get_bind()).get_table_names())
        if SettingsRecord.__tablename__ not in table_names:
            if not table_names:
                return
            raise RuntimeError("initialized database is missing the settings table")
        _verify_settings_encryption_fence(db, active_kid)
        rows = db.query(SettingsRecord).filter(SettingsRecord.key.in_(_SENSITIVE_KEYS)).all()
        for row in rows:
            _decrypt_sensitive_setting(row.key, row.value)
    finally:
        db.close()


def main() -> int:
    """Authenticate every persisted sensitive envelope without exposing values."""
    try:
        verify_persisted_sensitive_settings()
    except Exception:
        print(
            "settings encryption preflight failed; migrate legacy plaintext or "
            "repair the deployment keyring before upgrading",
            flush=True,
        )
        return 1
    print("settings encryption preflight passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
