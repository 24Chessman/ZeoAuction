"""Streaming consumer on ``bid.events`` (group ``fraud-detector``), #52.

A separate worker: it only reads ``bid.events``, so stopping it (or it falling behind) never
touches bidding. Offsets are committed manually after each event is folded into its window, so
a restart resumes from the last committed offset: at-least-once. Within a process a redelivered
event is recognised by its ``server_seq`` and dropped (``app/windows.py``). After a restart the
in-memory windows start empty; rebuilding them for still-open auctions is part of the Plan 5
scorer work (#55), and is why ``bid.events`` keeps 7 days.

Each accepted event is passed to :class:`app.features.FeatureExtractor` and the resulting
features to ``on_features``, the hook the shill scorer (Plan 5) plugs into.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge

from app.features import BidderFeatures, FeatureExtractor
from app.windows import AuctionWindows, Outcome

logger = logging.getLogger(__name__)

BID_EVENTS_TOPIC = "bid.events"
CONSUMER_GROUP = "fraud-detector"
REQUIRED = ("auction_id", "bidder_id", "server_seq", "accepted_at")

FeaturesHook = Callable[[BidderFeatures], Awaitable[None]]


class ConsumerMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.events = Counter("fraud_bid_events_total", "bid.events messages by outcome.",
                              ["outcome"], registry=registry)
        self.windows = Gauge("fraud_open_windows", "Auctions with a live sliding window.",
                             registry=registry)


@dataclass
class ConsumerStats:
    accepted: int = 0
    duplicate: int = 0
    skipped: int = 0
    # (topic, partition) -> next offset to read, as committed
    positions: dict[tuple[str, int], int] = field(default_factory=dict)


def decode(value: bytes) -> dict[str, Any] | None:
    try:
        event = json.loads(value)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        return None
    if any(key not in event for key in REQUIRED):
        return None
    try:
        int(event["server_seq"])
    except (TypeError, ValueError):
        return None
    return event


async def _ignore(_: BidderFeatures) -> None:
    return None


class FraudConsumer:
    """Wraps an ``aiokafka.AIOKafkaConsumer`` (injected so tests can fake the broker)."""

    def __init__(
        self,
        consumer: Any,
        *,
        windows: AuctionWindows | None = None,
        extractor: FeatureExtractor | None = None,
        metrics: ConsumerMetrics | None = None,
        on_features: FeaturesHook = _ignore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        expire_every: int = 500,
    ) -> None:
        self.consumer = consumer
        self.windows = windows or AuctionWindows()
        self.extractor = extractor or FeatureExtractor()
        self.metrics = metrics or ConsumerMetrics(CollectorRegistry())
        self.on_features = on_features
        self.clock = clock
        self.expire_every = expire_every
        self.stats = ConsumerStats()

    @classmethod
    def connect(cls, bootstrap_servers: str, **kwargs: Any) -> "FraudConsumer":  # pragma: no cover
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            BID_EVENTS_TOPIC,
            bootstrap_servers=bootstrap_servers,
            group_id=CONSUMER_GROUP,
            client_id="fraud-detector",
            enable_auto_commit=False,
            # A new group reads the whole retained topic (7 days): the dataset replay and
            # every still-open auction's history.
            auto_offset_reset="earliest",
        )
        return cls(consumer, **kwargs)

    async def handle(self, value: bytes) -> Outcome | None:
        event = decode(value)
        if event is None:
            self.stats.skipped += 1
            self.metrics.events.labels(outcome="skipped").inc()
            logger.warning("Skipping an unreadable or unknown-version bid.events message")
            return None
        outcome, _ = self.windows.add(event)
        self.metrics.events.labels(outcome=outcome.value).inc()
        if outcome is Outcome.DUPLICATE:
            self.stats.duplicate += 1
            return outcome
        self.stats.accepted += 1
        features = self.extractor.observe(event)
        if features is not None:
            try:
                await self.on_features(features)
            except Exception:
                logger.exception("Scoring hook failed for %s seq %s", event["auction_id"],
                                 event["server_seq"])
        if self.stats.accepted % self.expire_every == 0:
            self.expire()
        return outcome

    def expire(self) -> list[str]:
        expired = self.windows.expire(self.clock())
        for auction_id in expired:
            self.extractor.forget_auction(auction_id)
        self.metrics.windows.set(len(self.windows))
        return expired

    async def run(self) -> None:
        await self.consumer.start()
        try:
            async for message in self.consumer:
                await self.handle(message.value)
                await self.consumer.commit()
                self.stats.positions[(message.topic, message.partition)] = message.offset + 1
                self.metrics.windows.set(len(self.windows))
        finally:
            await self.consumer.stop()
