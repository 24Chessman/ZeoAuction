"""Kafka-driven fan-out (#93, SDD 7.8, Table 7.2).

A consumer on ``bid.events`` and ``auction.events`` turns events into WebSocket messages:

* ``BidAccepted`` -> ``price_update`` to everyone in the auction's room, and ``outbid`` to
  the displaced bidder only (every connection of that user, in any room). A bidder raising
  their own lead is not outbid.
* ``AuctionStateChanged`` ``extend`` -> ``auction_extended``; any transition to ``CLOSED`` ->
  ``auction_closed`` with the winning bid.

Fan-out runs on the consumer, never on a request thread, and only queues messages
(:class:`app.backpressure.Outbox`), so a slow watcher cannot slow a bidder or other watchers.
``ws_fanout_latency_seconds`` measures acceptance -> queued, the p95 < 100 ms target with 500
watchers. Events whose ``server_seq`` this gateway has already fanned out are skipped, and
unknown ``schema_version`` values are ignored (contracts/README.md, rule 4).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.connections import Hub
from app.rooms import RoomState, StaleSnapshot
from zeo_common import format_money, parse_money

logger = logging.getLogger(__name__)

BID_EVENTS = "bid.events"
AUCTION_EVENTS = "auction.events"

# Same tiers as the bid service's CT-3 stub until the Pricing Engine serves increments
# (Plan 4); a cached increment in Redis (inc:{auction_id}) wins when present.
INCREMENT_TIERS: tuple[tuple[Decimal | None, Decimal], ...] = (
    (Decimal("100.00"), Decimal("1.00")),
    (Decimal("500.00"), Decimal("5.00")),
    (Decimal("1000.00"), Decimal("10.00")),
    (Decimal("5000.00"), Decimal("25.00")),
    (None, Decimal("50.00")),
)


def tier_increment(price: Decimal) -> Decimal:
    for upper, increment in INCREMENT_TIERS:
        if upper is None or price < upper:
            return increment
    raise AssertionError("unreachable: the last tier is unbounded")


class Increments:
    def __init__(self, redis: Any | None = None) -> None:
        self.redis = redis

    async def for_price(self, auction_id: str, price: Decimal) -> Decimal:
        if self.redis is not None:
            try:
                cached = await self.redis.get(f"inc:{auction_id}")  # e.g. "5.00"
                if cached:
                    return parse_money(cached)
            except Exception:
                logger.debug("No usable cached increment for %s", auction_id)
        return tier_increment(price)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FanOut:
    def __init__(self, hub: Hub, increments: Increments | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.hub = hub
        self.increments = increments or Increments()
        self.clock = clock

    async def on_bid_accepted(self, event: dict[str, Any]) -> int:
        """Returns how many messages were queued."""
        if event.get("schema_version") != 1:
            return 0
        auction_id = event["auction_id"]
        amount = parse_money(event["amount"])
        state = RoomState(
            auction_id=auction_id,
            current_price=format_money(amount),
            min_next_bid=format_money(amount + await self.increments.for_price(auction_id,
                                                                               amount)),
            server_seq=int(event["server_seq"]),
            leader_bidder_id=event["bidder_id"],
            leader_bid_id=event["bid_id"],
        )
        try:
            previous = await self.hub.snapshots.advance(state)
        except StaleSnapshot:
            return 0  # redelivered or out of order: clients would discard it anyway
        update = state.price_update()
        watchers = self.hub.rooms.members(auction_id)
        for connection in watchers:
            connection.send(update)
        sent = len(watchers)
        if previous is not None and previous.leader_bidder_id != state.leader_bidder_id:
            outbid = {
                "type": "outbid",
                "auction_id": auction_id,
                "your_bid_id": previous.leader_bid_id,
                "current_price": state.current_price,
                "server_seq": state.server_seq,
            }
            for connection in self.hub.rooms.of_user(UUID(previous.leader_bidder_id)):
                connection.send(outbid)
                sent += 1
        lag = (self.clock() - _parse_time(event["accepted_at"])).total_seconds()
        self.hub.metrics.fanout_latency.observe(max(lag, 0.0))
        return sent

    async def on_auction_event(self, event: dict[str, Any]) -> int:
        if event.get("schema_version") != 1:
            return 0
        auction_id = event["auction_id"]
        if event.get("event") == "extend":
            message = {"type": "auction_extended", "auction_id": auction_id,
                       "new_closes_at": event["closes_at"]}
        elif event.get("to_state") == "CLOSED":
            message = {"type": "auction_closed", "auction_id": auction_id,
                       "winning_bid_id": event.get("winning_bid_id")}
        else:
            return 0
        watchers = self.hub.rooms.members(auction_id)
        for connection in watchers:
            connection.send(message)
        return len(watchers)

    async def dispatch(self, topic: str, value: bytes) -> None:
        try:
            event = json.loads(value)
        except (ValueError, UnicodeDecodeError):
            logger.warning("Skipping an unreadable %s message", topic)
            return
        if not isinstance(event, dict):
            return
        try:
            if topic == BID_EVENTS:
                await self.on_bid_accepted(event)
            elif topic == AUCTION_EVENTS:
                await self.on_auction_event(event)
        except (KeyError, ValueError, TypeError):
            logger.warning("Skipping a malformed %s event", topic)


class FanoutConsumer:
    """Wraps an ``aiokafka.AIOKafkaConsumer`` (injected so tests can fake it).

    Live push only: it starts at the latest offset, since a reconnecting client gets the
    snapshot instead of a replay. Every gateway instance needs its own consumer group
    (``WS_CONSUMER_GROUP``) so each one sees every event for its own connections.
    """

    def __init__(self, consumer: Any,
                 dispatch: Callable[[str, bytes], Awaitable[None]]) -> None:
        self.consumer = consumer
        self.dispatch = dispatch

    @classmethod
    def connect(cls, bootstrap_servers: str, group_id: str,
                dispatch: Callable[[str, bytes], Awaitable[None]]
                ) -> "FanoutConsumer":  # pragma: no cover - needs a broker
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            BID_EVENTS, AUCTION_EVENTS,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            client_id="ws-gateway",
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        return cls(consumer, dispatch)

    async def run(self) -> None:
        await self.consumer.start()
        try:
            async for message in self.consumer:
                try:
                    await self.dispatch(message.topic, message.value)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Fan-out of a %s message failed", message.topic)
        finally:
            await self.consumer.stop()
