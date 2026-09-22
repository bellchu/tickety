"""Fail-closed boundary for the retired Freshworks embedded session flow.

Freshworks Request Method protects secure installation parameters, but it does
not cryptographically attest browser-provided agent or ticket context to this
service. The former bootstrap protocol accepted those values as claims, so it
has been retired rather than made conditionally configurable. A future
replacement must perform a provider-authorized, server-side ticket access
check (for example, with a per-user OAuth token) before returning any local
ticket projection.
"""

from datetime import datetime
from typing import NoReturn, Optional

from sqlalchemy.orm import Session


class EmbeddedAuthError(ValueError):
    """Raised whenever retired embedded-session APIs are invoked."""


EMBEDDED_ACCESS_UNAVAILABLE_MESSAGE = "Freshworks embedded access is unavailable"


def _embedded_access_unavailable() -> NoReturn:
    """Keep legacy entry points disabled until real attestation exists.

    This must not become an environment switch: an operator cannot turn
    browser-controlled Freshworks Data Method values into a verifiable viewer
    assertion by enabling a deployment flag.
    """
    raise EmbeddedAuthError(EMBEDDED_ACCESS_UNAVAILABLE_MESSAGE)


def installation_secret_for_binding(binding_id: str) -> str:
    """Retired with the unauthenticated browser-to-backend bootstrap protocol."""
    _embedded_access_unavailable()


def verify_installation_secret(supplied: Optional[str], *, binding_id: str) -> None:
    """Retired with the unauthenticated browser-to-backend bootstrap protocol."""
    _embedded_access_unavailable()


def issue_bootstrap_code(
    db: Session,
    *,
    binding_id: str,
    account_host: str,
    external_user_id: str,
    workspace_id: Optional[str],
    external_ticket_id: Optional[str],
    ticket_updated_at: Optional[datetime],
    audience: str,
) -> tuple[str, datetime]:
    """Reject before querying or writing any legacy bootstrap record."""
    _embedded_access_unavailable()


def redeem_bootstrap_code(db: Session, *, binding_id: str, code: str):
    """Reject previously issued codes as well as new code redemption attempts."""
    _embedded_access_unavailable()


def authenticate_session(db: Session, authorization: Optional[str]):
    """Reject all previously issued embedded bearer tokens immediately."""
    _embedded_access_unavailable()


def require_ticket_scope(principal: object, external_ticket_id: str) -> None:
    """Prevent a future caller from treating a legacy principal as trustworthy."""
    _embedded_access_unavailable()
