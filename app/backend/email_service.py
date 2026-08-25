"""SendGrid-backed outbound email delivery.

Only this module knows the provider endpoint and authorization header.  Callers
pass already-authorized recipient addresses; the public API resolves opaque
directory IDs so it never becomes an arbitrary-address relay.
"""

from dataclasses import dataclass
from email.utils import parseaddr
import os
import re
from typing import Iterable

import httpx


SENDGRID_MAIL_SEND_URL = "https://api.sendgrid.com/v3/mail/send"
_EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}"
)


class EmailConfigurationError(RuntimeError):
    """Raised when outbound email has not been configured safely."""


class EmailDeliveryError(RuntimeError):
    """Raised when SendGrid does not accept a delivery request."""

    def __init__(self, provider_status: int | None = None):
        super().__init__("SendGrid did not accept the email")
        self.provider_status = provider_status


@dataclass(frozen=True)
class EmailAddress:
    email: str
    name: str


@dataclass(frozen=True)
class SendGridConfig:
    api_key: str
    from_email: str
    from_name: str
    reply_to_email: str | None


def normalize_email_address(value: str) -> str:
    """Return a canonical mailbox or raise without accepting display syntax."""
    candidate = str(value or "").strip().lower()
    _display_name, parsed = parseaddr(candidate)
    if (
        not candidate
        or len(candidate) > 320
        or parsed != candidate
        or not _EMAIL_PATTERN.fullmatch(candidate)
        or any(ord(character) < 33 or ord(character) == 127 for character in candidate)
    ):
        raise ValueError("Email address is invalid")
    return candidate


def normalize_sender_name(value: str) -> str:
    candidate = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(candidate) > 100 or any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        raise ValueError("Email sender name is invalid")
    return candidate


def get_sendgrid_config() -> SendGridConfig:
    api_key = (os.getenv("SENDGRID_API_KEY") or "").strip()
    from_email = (os.getenv("SENDGRID_FROM_EMAIL") or "").strip()
    from_name = (
        os.getenv("SENDGRID_FROM_NAME")
        or os.getenv("ORG_NAME")
        or "Tickety"
    )
    reply_to_email = (os.getenv("SENDGRID_REPLY_TO_EMAIL") or "").strip()
    if not api_key or not from_email:
        raise EmailConfigurationError("SendGrid API key and sender email are required")
    try:
        normalized_from = normalize_email_address(from_email)
        normalized_reply_to = (
            normalize_email_address(reply_to_email) if reply_to_email else None
        )
        normalized_name = normalize_sender_name(from_name)
    except ValueError as exc:
        raise EmailConfigurationError(str(exc)) from exc
    return SendGridConfig(
        api_key=api_key,
        from_email=normalized_from,
        from_name=normalized_name,
        reply_to_email=normalized_reply_to,
    )


def sendgrid_status() -> dict:
    api_key_set = bool((os.getenv("SENDGRID_API_KEY") or "").strip())
    from_email = (os.getenv("SENDGRID_FROM_EMAIL") or "").strip()
    try:
        from_name = normalize_sender_name(
            os.getenv("SENDGRID_FROM_NAME") or os.getenv("ORG_NAME") or "Tickety"
        )
    except ValueError:
        from_name = "Tickety"
    configured = False
    if api_key_set and from_email:
        try:
            get_sendgrid_config()
            configured = True
        except EmailConfigurationError:
            configured = False
    return {
        "provider": "sendgrid",
        "configured": configured,
        "api_key_set": api_key_set,
        "from_email_set": bool(from_email),
        "from_name": from_name,
    }


async def send_email(
    recipients: Iterable[EmailAddress],
    *,
    subject: str,
    body: str,
) -> str | None:
    config = get_sendgrid_config()
    unique_recipients: list[EmailAddress] = []
    seen: set[str] = set()
    for recipient in recipients:
        normalized = normalize_email_address(recipient.email)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_recipients.append(
            EmailAddress(email=normalized, name=normalize_sender_name(recipient.name))
        )
    if not unique_recipients:
        raise ValueError("At least one recipient is required")

    # A separate personalization keeps every recipient's address private from
    # the other recipients in the same application send.
    payload: dict = {
        "personalizations": [
            {"to": [{"email": recipient.email, "name": recipient.name}]}
            for recipient in unique_recipients
        ],
        "from": {"email": config.from_email, "name": config.from_name},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    if config.reply_to_email:
        payload["reply_to"] = {"email": config.reply_to_email}

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post(
                SENDGRID_MAIL_SEND_URL,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise EmailDeliveryError() from exc
    if response.status_code != 202:
        raise EmailDeliveryError(response.status_code)
    return response.headers.get("x-message-id")
