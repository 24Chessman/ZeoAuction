"""``ShillAlert v1`` producer on ``fraud.alerts``, keyed by ``auction_id`` (topics.yaml).

Dispute (#56) and admin moderation consume it in Plan 6.
"""

import json
from typing import Any

from app.alerts import FRAUD_ALERTS_TOPIC


def encode(alert: dict[str, Any]) -> tuple[bytes, bytes]:
    key = alert["auction_id"].encode("utf-8")
    value = json.dumps(alert, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return key, value


class KafkaAlertProducer:
    """Wraps an ``aiokafka.AIOKafkaProducer`` (injected so tests can fake it)."""

    def __init__(self, producer: Any, topic: str = FRAUD_ALERTS_TOPIC) -> None:
        self.producer = producer
        self.topic = topic

    @classmethod
    def connect(cls, bootstrap_servers: str, **kwargs: Any) -> "KafkaAlertProducer":  # pragma: no cover
        from aiokafka import AIOKafkaProducer
        from zeo_common import KafkaSettings

        kafka_kwargs = KafkaSettings.from_env().producer_kwargs()
        kafka_kwargs.update(kwargs)
        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id="fraud-detector",
            acks="all",
            enable_idempotence=True,
            request_timeout_ms=5000,
            **kafka_kwargs,
        )
        return cls(producer)

    async def start(self) -> None:
        await self.producer.start()

    async def stop(self) -> None:
        await self.producer.stop()

    async def publish(self, alert: dict[str, Any]) -> None:
        key, value = encode(alert)
        await self.producer.send_and_wait(self.topic, value=value, key=key)

    async def ready(self) -> bool:
        return bool(await self.producer.partitions_for(self.topic))


class InMemoryAlertProducer:
    """For tests, the evaluation harness and broker-less runs."""

    def __init__(self) -> None:
        self.alerts: list[dict[str, Any]] = []

    async def publish(self, alert: dict[str, Any]) -> None:
        self.alerts.append(alert)
