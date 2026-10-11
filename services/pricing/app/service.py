"""Pricing Engine use cases: observe accepted bids, serve CT-3, keep the hot set (#42-#44).

State lives in memory (velocity buckets, hot set) so CT-3 answers without I/O apart from the
``inc:{auction_id}`` cache write. Durable copies are written off the hot path: dirty buckets
by :meth:`PricingService.flush`, hot-flag changes when they happen. Run one replica: the
``pricing`` consumer group then owns every ``bid.events`` partition, so each auction's velocity
is complete in that process.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from prometheus_client import CollectorRegistry, Counter, Gauge

from app.adapters.bid_consumer import ObservedBid
from app.adapters.repository import PricingRepository, StoredBucket
from app.domain.hot_auction import HotAuctions, Transition
from app.domain.increment import (
    DEFAULT_LADDER,
    IncrementRule,
    min_increment,
    validate_ladder,
)
from app.domain.velocity import VelocityTracker
from zeo_common import format_money

logger = logging.getLogger(__name__)

# Persisted buckets are kept this long for monitoring, then pruned.
BUCKET_RETENTION = timedelta(hours=24)


def increment_cache_key(auction_id: UUID | str) -> str:
    return f"inc:{auction_id}"


@dataclass(frozen=True)
class IncrementQuote:
    auction_id: UUID
    min_increment: Decimal
    min_next_bid: Decimal
    hot: bool
    computed_at: datetime


@dataclass(frozen=True)
class Velocity:
    auction_id: UUID
    bids_per_minute: float
    hot: bool
    computed_at: datetime


class PricingMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.bids_observed = Counter(
            "pricing_bids_observed_total", "Accepted bids counted into velocity.",
            registry=registry)
        self.quotes = Counter(
            "pricing_increment_quotes_total", "CT-3 minimum-increment answers.", ["hot"],
            registry=registry)
        self.hot_auctions = Gauge(
            "pricing_hot_auctions", "Auctions currently flagged hot (FR-PRICE-3).",
            registry=registry)
        self.hot_changes = Counter(
            "pricing_hot_flag_changes_total", "Hot-flag transitions.", ["change"],
            registry=registry)


class PricingService:
    def __init__(
        self,
        *,
        tracker: VelocityTracker,
        hot: HotAuctions,
        repository: PricingRepository,
        cache: Any,
        metrics: PricingMetrics,
        saturation_bpm: float = 60.0,
        cache_ttl_seconds: int = 60,
        ladder: tuple[IncrementRule, ...] = DEFAULT_LADDER,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.tracker = tracker
        self.hot = hot
        self.repository = repository
        self.cache = cache
        self.metrics = metrics
        self.saturation_bpm = saturation_bpm
        self.cache_ttl_seconds = cache_ttl_seconds
        self.ladder = validate_ladder(ladder)
        self.clock = clock
        self._dirty: set[tuple[str, datetime]] = set()

    async def warm_up(self) -> None:
        """Load the ladder and restore the last window of velocity and the hot set."""
        self.ladder = validate_ladder(await self.repository.load_ladder())
        since = self.clock() - timedelta(seconds=self.tracker.window_seconds)
        for bucket in await self.repository.recent_buckets(since):
            self.tracker.restore(bucket.auction_id, bucket.start, bucket.count)
        self.hot.restore(await self.repository.active_flags())
        self.metrics.hot_auctions.set(self.hot.count())

    # ------------------------------------------------------------------ bid.events

    async def on_bid_accepted(self, bid: ObservedBid) -> None:
        bucket = self.tracker.record(bid.auction_id, bid.server_seq, bid.accepted_at)
        if bucket is None:
            return
        self.metrics.bids_observed.inc()
        self._dirty.add((bid.auction_id, bucket.start))
        now = self.clock()
        bpm = self.tracker.bids_per_minute(bid.auction_id, now)
        await self._evaluate(bid.auction_id, bpm, now)
        # The accepted amount is the new current price: keep the fallback warm for it.
        await self._cache(bid.auction_id, self._increment(bid.amount, bpm))

    # ------------------------------------------------------------------ CT-3

    async def quote(self, auction_id: UUID, current_price: Decimal) -> IncrementQuote:
        key = str(auction_id)
        now = self.clock()
        bpm = self.tracker.bids_per_minute(key, now)
        await self._evaluate(key, bpm, now)
        increment = self._increment(current_price, bpm)
        await self._cache(key, increment)
        hot = self.hot.is_hot(key)
        self.metrics.quotes.labels(hot=str(hot).lower()).inc()
        return IncrementQuote(auction_id, increment, current_price + increment, hot, now)

    async def velocity(self, auction_id: UUID) -> Velocity:
        key = str(auction_id)
        now = self.clock()
        bpm = self.tracker.bids_per_minute(key, now)
        await self._evaluate(key, bpm, now)
        return Velocity(auction_id, round(bpm, 3), self.hot.is_hot(key), now)

    # ------------------------------------------------------------------ background

    async def flush(self) -> int:
        """Persist dirty buckets, cool down quiet auctions and prune old history.
        Returns the number of buckets written."""
        now = self.clock()
        dirty, self._dirty = self._dirty, set()
        buckets = []
        for auction_id, start in sorted(dirty):
            count = self.tracker.bucket_count(auction_id, start)
            if count is not None:  # already pruned: outside the window, nothing to keep
                buckets.append(StoredBucket(auction_id, start, self.tracker.bucket_seconds,
                                            count))
        try:
            await self.repository.save_buckets(buckets)
        except Exception:
            self._dirty |= dirty  # retried on the next flush
            raise
        for auction_id in [a for a in self.tracker.auctions() if self.hot.is_hot(a)]:
            await self._evaluate(auction_id, self.tracker.bids_per_minute(auction_id, now), now)
        for auction_id in self.tracker.forget_idle(now):
            await self._evaluate(auction_id, 0.0, now)
        await self.repository.prune_buckets(now - BUCKET_RETENTION)
        return len(buckets)

    # ------------------------------------------------------------------ internals

    def _increment(self, current_price: Decimal, bpm: float) -> Decimal:
        return min_increment(self.ladder, current_price, bpm, self.saturation_bpm)

    async def _evaluate(self, auction_id: str, bpm: float, now: datetime) -> None:
        transition: Transition | None = self.hot.evaluate(auction_id, bpm, now)
        if transition is None:
            return
        logger.info("Auction %s %s: %s", auction_id, transition.change.value.lower(),
                    transition.reason)
        self.metrics.hot_changes.labels(change=transition.change.value).inc()
        self.metrics.hot_auctions.set(self.hot.count())
        try:
            await self.repository.record_flag(transition)
        except Exception:
            logger.exception("Could not persist the hot flag for %s", auction_id)

    async def _cache(self, auction_id: str, increment: Decimal) -> None:
        try:
            await self.cache.set(increment_cache_key(auction_id), format_money(increment),
                                 ex=self.cache_ttl_seconds)
        except Exception:
            logger.exception("Could not cache the increment for %s", auction_id)
