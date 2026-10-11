"""Rooms, the user index and the per-auction price snapshot (#93, #94; SDD 7.8, Table 4.3).

A room is the set of connections watching one auction. The user index finds every
connection of one user, so an ``outbid`` reaches the displaced bidder wherever they are
connected, and nobody else.

The snapshot is the latest ``price_update`` of an auction plus who leads it. It answers a
(re)subscribe with ``last_seq`` (FR-WS-3) and tells fan-out whom an accepted bid displaced.
It lives in Redis as the hash ``ws:room:{auction_id}`` (expires an hour after the last bid),
so a restarted gateway still knows the current price. It is never authoritative: it is
rebuilt from ``bid.events``.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

SNAPSHOT_TTL_SECONDS = 60 * 60


@dataclass(frozen=True)
class RoomState:
    auction_id: str
    current_price: str
    min_next_bid: str
    server_seq: int
    leader_bidder_id: str
    leader_bid_id: str

    def price_update(self) -> dict[str, Any]:
        return {
            "type": "price_update",
            "auction_id": self.auction_id,
            "current_price": self.current_price,
            "min_next_bid": self.min_next_bid,
            "server_seq": self.server_seq,
        }


class StaleSnapshot(Exception):
    """The event is not newer than what this gateway already fanned out."""


def snapshot_key(auction_id: str) -> str:
    return f"ws:room:{auction_id}"


# Compare-and-advance in one round trip: 1 if written, 0 if the stored one is as new.
_ADVANCE = """
local current = tonumber(redis.call('HGET', KEYS[1], 'server_seq') or '0')
if tonumber(ARGV[3]) <= current then return 0 end
redis.call('HSET', KEYS[1], 'current_price', ARGV[1], 'min_next_bid', ARGV[2],
           'server_seq', ARGV[3], 'leader_bidder_id', ARGV[4], 'leader_bid_id', ARGV[5])
redis.call('EXPIRE', KEYS[1], ARGV[6])
return 1
"""


def _from_hash(auction_id: str, values: dict[str, str]) -> RoomState | None:
    if not values or "server_seq" not in values:
        return None
    return RoomState(
        auction_id=auction_id,
        current_price=values["current_price"],
        min_next_bid=values["min_next_bid"],
        server_seq=int(values["server_seq"]),
        leader_bidder_id=values["leader_bidder_id"],
        leader_bid_id=values["leader_bid_id"],
    )


class RedisSnapshots:
    """The shared, persistent copy. Written best-effort; read when this instance has none."""

    def __init__(self, redis: Any, ttl_seconds: int = SNAPSHOT_TTL_SECONDS) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def get(self, auction_id: str) -> RoomState | None:
        return _from_hash(auction_id, await self.redis.hgetall(snapshot_key(auction_id)))

    async def advance(self, state: RoomState) -> bool:
        written = await self.redis.eval(
            _ADVANCE, 1, snapshot_key(state.auction_id), state.current_price,
            state.min_next_bid, state.server_seq, state.leader_bidder_id, state.leader_bid_id,
            self.ttl_seconds,
        )
        return bool(written)


class Snapshots:
    """Fan-out decisions use this instance's own cache, so every gateway instance (each with
    its own consumer group) fans out every event exactly once. Redis is the shared copy that
    lets a restarted instance answer a resubscribe before the next bid arrives."""

    def __init__(self, shared: RedisSnapshots | None = None) -> None:
        self.shared = shared
        self.local: dict[str, RoomState] = {}

    async def get(self, auction_id: str) -> RoomState | None:
        state = self.local.get(auction_id)
        if state is None and self.shared is not None:
            try:
                state = await self.shared.get(auction_id)
            except Exception:
                logger.warning("Reading the shared snapshot of %s failed", auction_id)
        return state

    async def advance(self, state: RoomState) -> RoomState | None:
        """Record ``state`` and return the one it replaced; :class:`StaleSnapshot` if this
        instance already fanned out an event as new or newer."""
        previous = await self.get(state.auction_id)
        if previous is not None and previous.server_seq >= state.server_seq:
            raise StaleSnapshot(state.auction_id)
        self.local[state.auction_id] = state
        if self.shared is not None:
            try:
                await self.shared.advance(state)
            except Exception:
                logger.warning("Writing the shared snapshot of %s failed", state.auction_id)
        return previous


class Rooms:
    """In-process membership. Each gateway instance knows only its own connections."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[Any]] = defaultdict(set)
        self._users: dict[UUID, set[Any]] = defaultdict(set)

    def connect(self, connection: Any) -> None:
        self._users[connection.user_id].add(connection)

    def disconnect(self, connection: Any) -> None:
        for auction_id in list(connection.rooms):
            self.leave(connection, auction_id)
        users = self._users.get(connection.user_id)
        if users is not None:
            users.discard(connection)
            if not users:
                del self._users[connection.user_id]

    def join(self, connection: Any, auction_id: str) -> None:
        self._rooms[auction_id].add(connection)
        connection.rooms.add(auction_id)

    def leave(self, connection: Any, auction_id: str) -> None:
        connection.rooms.discard(auction_id)
        members = self._rooms.get(auction_id)
        if members is not None:
            members.discard(connection)
            if not members:
                del self._rooms[auction_id]

    def members(self, auction_id: str) -> list[Any]:
        return list(self._rooms.get(auction_id, ()))

    def of_user(self, user_id: UUID) -> list[Any]:
        return list(self._users.get(user_id, ()))

    def connections_of(self, user_id: UUID) -> int:
        return len(self._users.get(user_id, ()))

    @property
    def room_count(self) -> int:
        return len(self._rooms)
