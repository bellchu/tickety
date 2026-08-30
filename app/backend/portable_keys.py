"""Cross-database normalization for administrator-defined ticket keys."""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"
_ASCII_LOWER_TRANSLATION = str.maketrans(ASCII_UPPER, ASCII_LOWER)


class _PortableAsciiLowerExpression(FunctionElement):
    type = String()
    inherit_cache = True


def _source_clause(element: _PortableAsciiLowerExpression):
    return next(iter(element.clauses))


@compiles(_PortableAsciiLowerExpression, "sqlite")
def _compile_sqlite_ascii_lower(element, compiler, **kwargs):
    # SQLite's built-in lower() intentionally changes ASCII letters only.
    expression = func.lower(func.trim(func.coalesce(_source_clause(element), "")))
    return compiler.process(expression, **kwargs)


@compiles(_PortableAsciiLowerExpression, "postgresql")
def _compile_postgresql_ascii_lower(element, compiler, **kwargs):
    # PostgreSQL lower() is locale/Unicode aware, so translate only ASCII.
    expression = func.translate(
        func.trim(func.coalesce(_source_clause(element), "")),
        ASCII_UPPER,
        ASCII_LOWER,
    )
    return compiler.process(expression, **kwargs)


@compiles(_PortableAsciiLowerExpression)
def _compile_generic_ascii_lower(element, compiler, **kwargs):
    expression = func.trim(func.coalesce(_source_clause(element), ""))
    for uppercase, lowercase in zip(ASCII_UPPER, ASCII_LOWER):
        expression = func.replace(expression, uppercase, lowercase)
    return compiler.process(expression, **kwargs)


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

    SQLite lower() already has the required ASCII-only behavior. PostgreSQL
    uses translate() so its locale-aware lower() cannot alias non-ASCII keys.
    Keeping this dispatch in one expression also prevents deeply nested SQL in
    queue and intelligence queries that reuse the normalized value many times.
    """
    return _PortableAsciiLowerExpression(value)
