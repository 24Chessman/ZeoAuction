"""``bid.events`` consumer (group ``pricing``) feeding velocity and the hot flag (#42).

At-least-once: offsets are committed only after the handler succeeded, and
:class:`app.domain.velocity.VelocityTracker` ignores a ``server_seq`` it already counted.
Unreadable events and unknown ``schema_version`` values are skipped, never fatal
(contracts/README.md, rule 4). Pricing is advisory, so a failing handler is logged and the
event skipped rather than blocking the partition.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from zeo_common import parse_money

logger = logging.getLogger(__name__)

BID_EVENTS_TOPIC = "bid.events"
CONSUMER_GROUP = "pricing"


@dataclass(frozen=True)
class ObservedBid:
    auction_id: str
    server_seq: int
    accepted_at: datetime
    amount: Decimal


def decode(value: bytes) -> ObservedBid | None:
    try:
        event = json.loads(value)
        if not isinstance(event, dict) or event.get("schema_version") != 1:
            return None
        return ObservedBid(
            auction_id=str(UUID(event["auction_id"])),
            server_seq=int(event["server_seq"]),
            accepted_at=datetime.fromisoformat(event["accepted_at"].replace("Z", "+00:00")),
            amount=parse_money(event["amount"]),
        )
    except (KeyError, ValueError, TypeError, AttributeError, UnicodeDecodeError):
        return None


Handler = Callable[[ObservedBid], Awaitable[Any]]


class BidEventsConsumer:
    """Wraps an ``aiokafka.AIOKafkaConsumer`` (injected so tests can fake it)."""

    def __init__(self, consumer: Any, handler: Handler) -> None:
        self.consumer = consumer
        self.handler = handler

    @classmethod
    def connect(cls, bootstrap_servers: str, handler: Handler,
                group_id: str = CONSUMER_GROUP) -> "BidEventsConsumer":  # pragma: no cover
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            BID_EVENTS_TOPIC,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            client_id="pricing",
            enable_auto_commit=False,
            # Velocity only looks back a minute: a new group starts at the head.
            auto_offset_reset="latest",
        )
        return cls(consumer, handler)

    async def handle(self, value: bytes) -> bool:
        bid = decode(value)
        if bid is None:
            logger.warning("Skipping an unreadable or unknown-version bid.events message")
            return False
        try:
            await self.handler(bid)
        except Exception:
            logger.exception("Pricing could not apply bid seq %s of %s; skipped",
                             bid.server_seq, bid.auction_id)
            return False
        return True

    async def run(self) -> None:
        await self.consumer.start()
        try:
            async for message in self.consumer:
                await self.handle(message.value)
                await self.consumer.commit()
        finally:
            await self.consumer.stop()
