"""Connection management: authenticated handshake, limits and the per-connection writer (#92).

Handshake (SDD 7.8): the access token travels as the ``access_token`` query parameter (a
browser cannot set headers on a WebSocket) or as ``Authorization: Bearer``. It is verified
locally, like every other service (ADR-0005). The socket is accepted first and then closed
with **4401** if the token is missing, invalid or expired, because a browser only sees close
codes, never an HTTP status; the client refreshes and reconnects at once.

Limits, each with its own close code so the client can tell them apart:

| Limit | Default | When exceeded |
|---|---|---|
| Connections per user | 5 | close 4429 |
| Rooms per connection | 50 | ``error`` message, subscription refused |
| Client messages per second | 20 | close 4429 |
| Silence (client pings every 25 s) | 75 s | close 4408 |
| Undelivered non-price messages | 256 | close 1013, the client resubscribes for a snapshot |

The socket carries no commands: bids are placed over REST (FR-WS-1, IR-COM-2).
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import jwt
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from app.backpressure import Outbox, OutboxClosed, OutboxOverflow
from app.rooms import Rooms, Snapshots
from zeo_common import ApiError
from zeo_common.auth import JwtSettings, Principal, decode_access_token

logger = logging.getLogger(__name__)

CLOSE_NORMAL = 1000
CLOSE_TRY_AGAIN_LATER = 1013
CLOSE_TOKEN_EXPIRED = 4401
CLOSE_IDLE = 4408
CLOSE_RATE_LIMITED = 4429


@dataclass(frozen=True)
class Limits:
    max_connections_per_user: int = 5
    max_subscriptions: int = 50
    max_messages_per_second: int = 20
    idle_timeout_seconds: float = 75.0
    outbox_limit: int = 256


class GatewayMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.connections = Gauge("ws_connections", "Open WebSocket connections.",
                                 registry=registry)
        self.rejected = Counter("ws_handshakes_rejected", "Refused handshakes, by reason.",
                                ["reason"], registry=registry)
        self.fanout_latency = Histogram(
            "ws_fanout_latency_seconds",
            "From a bid's acceptance to its price_update being queued for every watcher.",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.25, 0.5, 1.0, 2.5),
            registry=registry,
        )
        self.messages = Counter("ws_messages_sent", "Messages queued to clients, by type.",
                                ["type"], registry=registry)
        self.coalesced = Counter("ws_price_updates_coalesced",
                                 "Intermediate price_update messages replaced by a newer one.",
                                 registry=registry)
        self.slow_disconnects = Counter(
            "ws_slow_consumer_disconnects",
            "Connections closed because they could not keep up.", registry=registry,
        )


class HandshakeRefused(Exception):
    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def token_from(query_params: Any, headers: Any) -> str | None:
    token = query_params.get("access_token")
    if token:
        return token
    scheme, _, value = headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def authenticate(settings: JwtSettings, token: str | None) -> tuple[Principal, datetime]:
    """The verified principal and the token's expiry, or :class:`HandshakeRefused`."""
    if not token:
        raise HandshakeRefused(CLOSE_TOKEN_EXPIRED, "missing token")
    try:
        principal = decode_access_token(settings, token)
    except ApiError as exc:
        raise HandshakeRefused(CLOSE_TOKEN_EXPIRED, "invalid or expired token") from exc
    # Signature, issuer, audience and expiry were verified just above.
    claims = jwt.decode(token, options={"verify_signature": False})
    return principal, datetime.fromtimestamp(claims["exp"], UTC)


class Connection:
    """One socket. Fan-out calls :meth:`send` (never blocks); :meth:`write_loop` drains."""

    def __init__(self, socket: Any, principal: Principal, expires_at: datetime,
                 limits: Limits, metrics: GatewayMetrics) -> None:
        self.id = uuid4()
        self.socket = socket
        self.principal = principal
        self.expires_at = expires_at
        self.limits = limits
        self.metrics = metrics
        self.rooms: set[str] = set()
        self.outbox = Outbox(limits.outbox_limit)
        self.close_code: int | None = None
        self._window_start = time.monotonic()
        self._window_count = 0

    @property
    def user_id(self) -> UUID:
        return self.principal.user_id

    def token_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def send(self, message: dict[str, Any]) -> None:
        if self.close_code is not None:
            return
        try:
            if self.outbox.put(message):
                self.metrics.coalesced.inc()
        except OutboxOverflow:
            self.metrics.slow_disconnects.inc()
            logger.info("Closing slow connection %s of user %s", self.id, self.user_id)
            self.close(CLOSE_TRY_AGAIN_LATER)
            return
        self.metrics.messages.labels(type=message.get("type", "unknown")).inc()

    def allow_message(self) -> bool:
        """Fixed one-second window on client messages."""
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._window_start, self._window_count = now, 0
        self._window_count += 1
        return self._window_count <= self.limits.max_messages_per_second

    def close(self, code: int) -> None:
        """Stop delivering and ask the socket to close; idempotent."""
        if self.close_code is not None:
            return
        self.close_code = code
        self.outbox.close()

    async def write_loop(self) -> None:
        try:
            while True:
                message = await self.outbox.get()
                await self.socket.send_json(message)
        except OutboxClosed:
            pass
        finally:
            if self.close_code is not None:
                with contextlib.suppress(Exception):
                    await self.socket.close(self.close_code)


class Hub:
    """Everything the endpoint and fan-out share."""

    def __init__(self, jwt_settings: JwtSettings, metrics: GatewayMetrics,
                 snapshots: Snapshots | None = None, limits: Limits | None = None) -> None:
        self.jwt_settings = jwt_settings
        self.metrics = metrics
        self.snapshots = snapshots or Snapshots()
        self.limits = limits or Limits()
        self.rooms = Rooms()

    def open(self, socket: Any, token: str | None) -> Connection:
        try:
            principal, expires_at = authenticate(self.jwt_settings, token)
        except HandshakeRefused as refused:
            self.metrics.rejected.labels(reason="token").inc()
            raise refused
        if self.rooms.connections_of(principal.user_id) >= self.limits.max_connections_per_user:
            self.metrics.rejected.labels(reason="too_many_connections").inc()
            raise HandshakeRefused(CLOSE_RATE_LIMITED, "too many connections")
        connection = Connection(socket, principal, expires_at, self.limits, self.metrics)
        self.rooms.connect(connection)
        self.metrics.connections.inc()
        return connection

    def release(self, connection: Connection) -> None:
        self.rooms.disconnect(connection)
        self.metrics.connections.dec()

    async def handle(self, connection: Connection, message: Any,
                     now: datetime | None = None) -> None:
        """Apply one client message (already parsed JSON)."""
        if not connection.allow_message():
            connection.close(CLOSE_RATE_LIMITED)
            return
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "ping":
            connection.send({"type": "pong"})
        elif kind == "subscribe":
            await self._subscribe(connection, message, now or datetime.now(UTC))
        elif kind == "unsubscribe" and _auction_id(message):
            self.rooms.leave(connection, _auction_id(message))
        else:
            connection.send(error("BAD_REQUEST", "Unknown or malformed message"))

    async def _subscribe(self, connection: Connection, message: dict, now: datetime) -> None:
        if connection.token_expired(now):
            # SDD 7.8: a subscribe on an expired token is refused; refresh and reconnect.
            connection.close(CLOSE_TOKEN_EXPIRED)
            return
        auction_id = _auction_id(message)
        last_seq = message.get("last_seq", 0)
        if auction_id is None or not isinstance(last_seq, int) or isinstance(last_seq, bool):
            connection.send(error("BAD_REQUEST", "subscribe needs auction_id and an integer "
                                  "last_seq"))
            return
        if auction_id not in connection.rooms and \
                len(connection.rooms) >= self.limits.max_subscriptions:
            connection.send(error("RATE_LIMITED", "Too many rooms on one connection",
                                  auction_id))
            return
        self.rooms.join(connection, auction_id)
        # FR-WS-3: the snapshot closes any gap since the client's last server_seq.
        snapshot = await self.snapshots.get(auction_id)
        if snapshot is not None and snapshot.server_seq > last_seq:
            connection.send(snapshot.price_update())


def _auction_id(message: dict) -> str | None:
    try:
        return str(UUID(str(message.get("auction_id"))))
    except ValueError:
        return None


def error(code: str, message: str, auction_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "error", "code": code, "message": message}
    if auction_id:
        body["auction_id"] = auction_id
    return body


async def wait_closed(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
