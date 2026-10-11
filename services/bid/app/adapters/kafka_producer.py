"""``BidAccepted v1`` producer on ``bid.events`` (#29; contracts/events/bid_accepted.v1.json).

Keyed by ``auction_id``, so every bid for one auction lands on one partition in
``server_seq`` order (contracts/events/topics.yaml). :meth:`KafkaBidEventPublisher.publish`
returns only after the broker acknowledges the write (``acks=all``); the bid service
acknowledges the client after that, so an accepted bid is always recoverable from Kafka.
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from zeo_common import format_money

BID_EVENTS_TOPIC = "bid.events"
SCHEMA_VERSION = 1


def iso_utc(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def build_bid_accepted(
    *,
    event_id: UUID,
    bid_id: UUID,
    auction_id: UUID,
    bidder_id: UUID,
    seller_id: UUID,
    amount: Decimal,
    currency: str,
    server_seq: int,
    accepted_at: datetime,
    auction_closes_at: datetime | None,
    idempotency_key: str,
    device_fingerprint: str | None,
    increment_stale: bool,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_id": str(event_id),
        "schema_version": SCHEMA_VERSION,
        "auction_id": str(auction_id),
        "bid_id": str(bid_id),
        "bidder_id": str(bidder_id),
        "seller_id": str(seller_id),
        "amount": format_money(amount),
        "currency": currency,
        "server_seq": server_seq,
        "accepted_at": iso_utc(accepted_at),
        "idempotency_key": idempotency_key,
        "device_fingerprint": device_fingerprint,
        "increment_stale": increment_stale,
    }
    if auction_closes_at is not None:
        event["auction_closes_at"] = iso_utc(auction_closes_at)
    return event


def encode(event: dict[str, Any]) -> tuple[bytes, bytes]:
    """(key, value) as written to Kafka."""
    key = event["auction_id"].encode("utf-8")
    value = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return key, value


class BidEventPublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...


class KafkaBidEventPublisher:
    """Wraps an ``aiokafka.AIOKafkaProducer`` (injected so tests can fake it)."""

    def __init__(self, producer: Any, topic: str = BID_EVENTS_TOPIC) -> None:
        self.producer = producer
        self.topic = topic

    @classmethod
    def connect(cls, bootstrap_servers: str) -> "KafkaBidEventPublisher":
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id="bid",
            acks="all",
            enable_idempotence=True,  # a retried send never duplicates an event
            linger_ms=1,
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


class InMemoryBidEventPublisher:
    """For tests and broker-less local runs. ``fail_next`` simulates a broker outage."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail_next = False

    async def publish(self, event: dict[str, Any]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("broker unavailable")
        self.events.append(event)
