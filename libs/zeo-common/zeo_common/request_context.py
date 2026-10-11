"""Per-request correlation id, carried in the ``X-Request-ID`` header and every error body."""

import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = b"x-request-id"

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Return the current request id, or a fresh one outside a request."""
    return _request_id.get() or str(uuid.uuid4())


def _parse_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


class RequestIdMiddleware:
    """Accept a caller-supplied UUID request id or mint one, and echo it on the response.

    Written as plain ASGI (not ``BaseHTTPMiddleware``) so the context variable stays
    visible to exception handlers further out in the stack.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(REQUEST_ID_HEADER, b"")
        request_id = _parse_uuid(incoming.decode("latin-1")) or str(uuid.uuid4())
        _request_id.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)
