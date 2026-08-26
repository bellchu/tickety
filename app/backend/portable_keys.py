"""Cross-database normalization for administrator-defined ticket keys."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func


ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"
_ASCII_LOWER_TRANSLATION = str.maketrans(ASCII_UPPER, ASCII_LOWER)


def portable_ascii_lower(value: object) -> str:
    """Trim ordinary spaces and lowercase ASCII letters only.

    Ticket status and priority values can originate with external providers,
    while configurable keys are deliberately portable ASCII. Unicode lower()
    differs between Python, SQLite, and PostgreSQL (for example K and İ), so
    non-ASCII characters must remain untouched and therefore cannot alias an
    ASCII configuration key.
    """
    return str(value or "").strip(" ").translate(_ASCII_LOWER_TRANSLATION)


def portable_ascii_lower_expression(value: Any):
    """Return the SQL equivalent of :func:`portable_ascii_lower`.

    SQLAlchemy supports replace() and trim() on both SQLite and PostgreSQL.
    Chaining the 26 ASCII replacements avoids each database's incompatible
    Unicode lower() implementation.
    """
    expression = func.trim(func.coalesce(value, ""))
    for uppercase, lowercase in zip(ASCII_UPPER, ASCII_LOWER):
        expression = func.replace(expression, uppercase, lowercase)
    return expression
