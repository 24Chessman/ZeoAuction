"""``bid.events`` consumer (group ``auction-orchestrator``) feeding anti-snipe and the leader.

At-least-once: offsets are committed only after the handler succeeded, so a crash replays the
uncommitted events, and :func:`app.domain.anti_snipe.apply_bid` ignores any ``server_seq`` it
has already applied. Events with an unknown ``schema_version`` are skipped, never fatal
(contracts/README.md, rule 4).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.anti_snipe import AcceptedBid
from zeo_common import parse_money

logger = logging.getLogger(__name__)

BID_EVENTS_TOPIC = "bid.events"
CONSUMER_GROUP = "auction-orchestrator"
RETRY_SECONDS = 1.0


def parse_accepted(event: dict[str, Any]) -> AcceptedBid | None:
    if event.get("schema_version") != 1:
        return None
    try:
        return AcceptedBid(
            auction_id=UUID(event["auction_id"]),
            bid_id=UUID(event["bid_id"]),
            server_seq=int(event["server_seq"]),
            accepted_at=datetime.fromisoformat(event["accepted_at"].replace("Z", "+00:00")),
            bidder_id=UUID(event["bidder_id"]),
            amount=parse_money(event["amount"]),
        )
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def decode(value: bytes) -> AcceptedBid | None:
    try:
        event = json.loads(value)
    except (ValueError, UnicodeDecodeError):
        return None
    return parse_accepted(event) if isinstance(event, dict) else None


Handler = Callable[[AcceptedBid], Awaitable[Any]]


class BidEventsConsumer:
    """Wraps an ``aiokafka.AIOKafkaConsumer`` (injected so tests can fake it)."""

    def __init__(self, consumer: Any, handler: Handler,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.consumer = consumer
        self.handler = handler
        self._sleep = sleep

    @classmethod
    def connect(cls, bootstrap_servers: str, handler: Handler,
                group_id: str = CONSUMER_GROUP) -> "BidEventsConsumer":  # pragma: no cover
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            BID_EVENTS_TOPIC,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            client_id="auction-orchestrator",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        return cls(consumer, handler)

    async def handle(self, value: bytes) -> None:
        """Apply one message, retrying until it succeeds (a skipped bid would lose an
        extension or the leader)."""
        bid = decode(value)
        if bid is None:
            logger.warning("Skipping an unreadable or unknown-version bid.events message")
            return
        while True:
            try:
                await self.handler(bid)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Applying bid %s failed; retrying", bid.bid_id)
                await self._sleep(RETRY_SECONDS)

    async def run(self) -> None:
        await self.consumer.start()
        try:
            async for message in self.consumer:
                await self.handle(message.value)
                await self.consumer.commit()
        finally:
            await self.consumer.stop()
