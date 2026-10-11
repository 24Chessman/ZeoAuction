"""``SettlementStep v1`` producer on ``payment.events`` (#33; contract
contracts/events/settlement_step.v1.json).

Published after every committed settlement step, keyed by ``order_id`` so one order's steps
stay in order (the topic is compacted to the latest step per order). Auction Orchestration
consumes ``HELD`` to apply A7 ``settle``; the WebSocket gateway and search consume it too.
Publishing happens after the commit: if the broker is down the step stands, and the failure is
logged and counted (``payment_events_publish_failures``).
"""

import json
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.orders import Order
from zeo_common import format_money

PAYMENT_EVENTS_TOPIC = "payment.events"
SCHEMA_VERSION = 1
STEP_TYPES = ("INVOICED", "CAPTURED", "HELD", "SHIPPED", "DISPUTED", "RELEASED", "REFUNDED",
              "COMPENSATED")
# The idempotency key of the money movement each step records.
STEP_OPERATION = {"INVOICED": "invoice", "CAPTURED": "capture", "HELD": "hold",
                  "COMPENSATED": "compensate-s1"}


def iso_utc(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def build_settlement_step(*, event_id: UUID, order: Order, step: str,
                          occurred_at: datetime) -> dict[str, Any]:
    if step not in STEP_TYPES:
        raise ValueError(f"unknown settlement step {step}")
    return {
        "event_id": str(event_id),
        "schema_version": SCHEMA_VERSION,
        "order_id": str(order.id),
        "auction_id": str(order.auction_id),
        "type": step,
        "gross": format_money(order.captured_total),
        "fee": format_money(order.convenience_fee),
        "net": format_money(order.captured_total - order.convenience_fee),
        "currency": order.currency,
        "fee_version": order.fee_version,
        "saga_id": str(order.saga_id),
        "idempotency_key": order.idempotency_key(STEP_OPERATION.get(step, step.lower())),
        "occurred_at": iso_utc(occurred_at),
    }


def encode(event: dict[str, Any]) -> tuple[bytes, bytes]:
    key = event["order_id"].encode("utf-8")
    value = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return key, value


class SettlementEventPublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...


class KafkaSettlementEventPublisher:
    """Wraps an ``aiokafka.AIOKafkaProducer`` (injected so tests can fake it)."""

    def __init__(self, producer: Any, topic: str = PAYMENT_EVENTS_TOPIC) -> None:
        self.producer = producer
        self.topic = topic

    @classmethod
    def connect(cls, bootstrap_servers: str) -> "KafkaSettlementEventPublisher":
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id="payment-escrow",
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


class InMemorySettlementEventPublisher:
    """For tests and broker-less local runs. ``fail_next`` simulates a broker outage."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail_next = False

    async def publish(self, event: dict[str, Any]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("broker unavailable")
        self.events.append(event)

    def types(self, order_id: UUID | None = None) -> list[str]:
        return [e["type"] for e in self.events
                if order_id is None or e["order_id"] == str(order_id)]
