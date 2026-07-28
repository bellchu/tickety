"""Transport-level safety controls shared by the HTTP API.

Application schemas still own field-level validation.  This middleware exists
to reject an oversized body before Starlette or Pydantic buffers and parses it.
"""

import os
from typing import Awaitable, Callable

from starlette.responses import JSONResponse


class _RequestBodyTooLarge(Exception):
    pass


def _body_limit_bytes() -> int:
    try:
        configured = int(os.getenv("MAX_REQUEST_BODY_BYTES", "1048576"))
    except (TypeError, ValueError):
        configured = 1_048_576
    return max(16_384, min(configured, 10_485_760))


class RequestBodyLimitMiddleware:
    """Bound unsafe HTTP request bodies, including chunked requests."""

    def __init__(self, app, max_body_bytes: int | None = None):
        self.app = app
        self.max_body_bytes = max_body_bytes or _body_limit_bytes()

    async def __call__(self, scope, receive: Callable[[], Awaitable[dict]], send):
        if scope.get("type") != "http" or scope.get("method", "GET").upper() not in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            await self.app(scope, receive, send)
            return

        content_lengths = []
        transfer_encoding = False
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    content_lengths.append(int(value.decode("ascii")))
                except (UnicodeDecodeError, ValueError):
                    await JSONResponse(
                        {"detail": "invalid_content_length"}, status_code=400
                    )(scope, receive, send)
                    return
            elif key.lower() == b"transfer-encoding":
                transfer_encoding = True
        if (
            any(length < 0 for length in content_lengths)
            or len(content_lengths) > 1
            or (content_lengths and transfer_encoding)
        ):
            await JSONResponse(
                {"detail": "invalid_content_length"}, status_code=400
            )(scope, receive, send)
            return
        if content_lengths and content_lengths[0] > self.max_body_bytes:
            await JSONResponse(
                {"detail": "request_body_too_large"}, status_code=413
            )(scope, receive, send)
            return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await JSONResponse(
                {"detail": "request_body_too_large"}, status_code=413
            )(scope, receive, send)
