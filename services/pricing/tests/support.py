"""Builders shared by the pricing tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import fakeredis
from prometheus_client import CollectorRegistry

from app.adapters.bid_consumer import ObservedBid
from app.adapters.repository import InMemoryPricingRepository
from app.domain.hot_auction import HotAuctions, HotPolicy
from app.domain.velocity import VelocityTracker
from app.service import PricingMetrics, PricingService

AUCTION = UUID("00000000-0000-4000-8000-000000000201")
OTHER = UUID("00000000-0000-4000-8000-000000000202")
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def bid(seq: int, at: datetime, amount: str = "100.00",
        auction: UUID = AUCTION) -> ObservedBid:
    return ObservedBid(str(auction), seq, at, Decimal(amount))


def make_service(clock: Clock | None = None, repository: InMemoryPricingRepository | None = None,
                 cache: object | None = None) -> PricingService:
    return PricingService(
        tracker=VelocityTracker(60, 5),
        hot=HotAuctions(HotPolicy(enter_bpm=30, exit_bpm=15)),
        repository=repository or InMemoryPricingRepository(),
        cache=cache if cache is not None else fakeredis.FakeAsyncRedis(decode_responses=True),
        metrics=PricingMetrics(CollectorRegistry()),
        saturation_bpm=60,
        cache_ttl_seconds=60,
        clock=clock or Clock(),
    )
