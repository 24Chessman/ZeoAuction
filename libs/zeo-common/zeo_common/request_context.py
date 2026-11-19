"""Per-request correlation id, carried in the ``X-Request-ID`` header and every error body."""

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = b"x-request-id"

_request_id: ContextVar[str] = ContextVar("request_id", default="")
logger = logging.getLogger("zeo.http")


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
    visible to exception handlers further out in the stack. Also logs incoming requests
    and outgoing responses with duration and status code.
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

        method = scope.get("method", "WS" if scope["type"] == "websocket" else "HTTP")
        path = scope.get("path", "")
        is_probe = path in ("/healthz", "/readyz", "/metrics")

        if not is_probe:
            client = scope.get("client")
            client_ip = client[0] if client else "unknown"
            logger.info("--> %s %s from %s", method, path, client_ip)

        start_time = time.perf_counter()
        status_code = 200

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception("<-- EXCEPTION %s %s (%sms): %s", method, path, duration_ms, exc)
            raise
        else:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            if not is_probe:
                if status_code < 400:
                    logger.info("<-- %s %s %s (%sms)", method, path, status_code, duration_ms)
                elif status_code < 500:
                    logger.warning("<-- %s %s %s (%sms)", method, path, status_code, duration_ms)
                else:
                    logger.error("<-- %s %s %s (%sms)", method, path, status_code, duration_ms)
