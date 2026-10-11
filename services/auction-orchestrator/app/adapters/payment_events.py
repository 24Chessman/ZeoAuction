"""``payment.events`` consumer (group ``auction-orchestrator``) applying A7 ``settle`` (#33).

Payment publishes ``SettlementStep v1`` for every settlement step; ``HELD`` means the winner's
payment is captured and held in escrow, which is A7's guard ("payment reports the order
IN_ESCROW"). At-least-once: offsets are committed only after the handler succeeded, and
applying ``settle`` to an auction that is already SETTLED is a no-op. Events with an unknown
``schema_version`` are skipped, never fatal (contracts/README.md, rule 4).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

PAYMENT_EVENTS_TOPIC = "payment.events"
CONSUMER_GROUP = "auction-orchestrator"
RETRY_SECONDS = 1.0


@dataclass(frozen=True)
class SettlementStep:
    """The fields of ``SettlementStep v1`` the orchestrator uses."""

    auction_id: UUID
    order_id: UUID
    type: str


def decode(value: bytes) -> SettlementStep | None:
    try:
        event = json.loads(value)
        if not isinstance(event, dict) or event.get("schema_version") != 1:
            return None
        return SettlementStep(auction_id=UUID(event["auction_id"]),
                              order_id=UUID(event["order_id"]), type=str(event["type"]))
    except (ValueError, UnicodeDecodeError, KeyError, TypeError):
        return None


Handler = Callable[[SettlementStep], Awaitable[Any]]


class PaymentEventsConsumer:
    """Wraps an ``aiokafka.AIOKafkaConsumer`` (injected so tests can fake it)."""

    def __init__(self, consumer: Any, handler: Handler,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.consumer = consumer
        self.handler = handler
        self._sleep = sleep

    @classmethod
    def connect(cls, bootstrap_servers: str, handler: Handler,
                group_id: str = CONSUMER_GROUP) -> "PaymentEventsConsumer":  # pragma: no cover
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            PAYMENT_EVENTS_TOPIC,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            client_id="auction-orchestrator",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        return cls(consumer, handler)

    async def handle(self, value: bytes) -> None:
        step = decode(value)
        if step is None:
            logger.warning("Skipping an unreadable or unknown-version payment.events message")
            return
        while True:
            try:
                await self.handler(step)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Applying settlement step %s of order %s failed; retrying",
                                 step.type, step.order_id)
                await self._sleep(RETRY_SECONDS)

    async def run(self) -> None:
        await self.consumer.start()
        try:
            async for message in self.consumer:
                await self.handle(message.value)
                await self.consumer.commit()
        finally:
            await self.consumer.stop()
