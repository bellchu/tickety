#!/usr/bin/env python3
"""Explicitly migrate or rotate encrypted SettingsRecord secrets."""

from __future__ import annotations

import argparse

from app.backend.settings import reencrypt_persisted_sensitive_settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-encrypt persisted sensitive settings using the active deployment KID."
    )
    parser.add_argument(
        "--allow-legacy-plaintext",
        action="store_true",
        help="explicitly migrate detected legacy plaintext settings",
    )
    parser.add_argument(
        "--from-kid",
        help=(
            "required when rotating to a different active KID; must exactly match "
            "the durable previous KID"
        ),
    )
    args = parser.parse_args()
    result = reencrypt_persisted_sensitive_settings(
        allow_legacy_plaintext=args.allow_legacy_plaintext,
        from_kid=args.from_kid,
    )
    print(
        "settings secret re-encryption completed "
        f"migrated_plaintext={result['migrated_plaintext']} "
        f"reencrypted={result['reencrypted']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
