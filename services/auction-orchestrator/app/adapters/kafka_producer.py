"""``AuctionStateChanged v1`` producer on ``auction.events`` (#32; contract
contracts/events/auction_state_changed.v1.json).

Published after every committed lifecycle transition, keyed by ``auction_id`` so one auction's
transitions stay in order. The WebSocket gateway turns ``extend`` into ``auction_extended``
and a transition to CLOSED into ``auction_closed``; search and payment consume it too.

The frozen v1 ``event`` enum has no ``drained``: the CLOSING -> CLOSED step (A6) is published
as ``close`` with ``from_state = CLOSING``, so consumers key off ``to_state``. Adding
``drained`` to the enum is a contract change for the interface owner (contracts/README.md).
"""

import json
import logging
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.auction import Auction

logger = logging.getLogger(__name__)

AUCTION_EVENTS_TOPIC = "auction.events"
SCHEMA_VERSION = 1
# Lifecycle event name -> the v1 contract's name.
CONTRACT_EVENT = {
    "publish": "publish",
    "open": "open",
    "extend": "extend",
    "close": "close",
    "drained": "close",
    "settle": "settle",
    "cancel": "cancel",
}


def iso_utc(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def build_state_changed(
    *, event_id: UUID, before: Auction, after: Auction, event: str, actor_id: UUID | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": str(event_id),
        "schema_version": SCHEMA_VERSION,
        "auction_id": str(after.id),
        "event": CONTRACT_EVENT[event],
        "from_state": before.state,
        "to_state": after.state,
        "closes_at": None if after.closes_at is None else iso_utc(after.closes_at),
        "extension_count": after.extension_count,
        "winning_bid_id": None if after.winning_bid_id is None else str(after.winning_bid_id),
        "actor_id": None if actor_id is None else str(actor_id),
        "occurred_at": iso_utc(occurred_at),
    }


def encode(event: dict[str, Any]) -> tuple[bytes, bytes]:
    key = event["auction_id"].encode("utf-8")
    value = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return key, value


class AuctionEventPublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...


class KafkaAuctionEventPublisher:
    """Wraps an ``aiokafka.AIOKafkaProducer`` (injected so tests can fake it)."""

    def __init__(self, producer: Any, topic: str = AUCTION_EVENTS_TOPIC) -> None:
        self.producer = producer
        self.topic = topic

    @classmethod
    def connect(cls, bootstrap_servers: str) -> "KafkaAuctionEventPublisher":
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id="auction-orchestrator",
            acks="all",
            enable_idempotence=True,
            request_timeout_ms=5000,
        )
        return cls(producer)

    async def start(self) -> None:
        await self.producer.start()

    async def stop(self) -> None:
        await self.producer.stop()

    async def publish(self, event: dict[str, Any]) -> None:
        key, value = encode(event)
        await self.producer.send_and_wait(self.topic, value=value, key=key)

    async def ready(self) -> bool:
        return bool(await self.producer.partitions_for(self.topic))


class InMemoryAuctionEventPublisher:
    """For tests and broker-less local runs. ``fail_next`` simulates a broker outage."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail_next = False

    async def publish(self, event: dict[str, Any]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("broker unavailable")
        self.events.append(event)
