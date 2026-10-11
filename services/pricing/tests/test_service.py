from datetime import timedelta
from decimal import Decimal

import fakeredis
import pytest

from app.adapters.repository import InMemoryPricingRepository, StoredBucket
from app.domain.hot_auction import Change
from app.domain.increment import IncrementRule
from app.service import increment_cache_key
from tests.support import AUCTION, OTHER, T0, Clock, bid, make_service


async def burst(service, clock, n, *, amount="1200.00", start_seq=1, auction=AUCTION):
    for i in range(n):
        await service.on_bid_accepted(bid(start_seq + i, clock.now, amount, auction))
        clock.advance(1)


async def test_quote_without_bids_is_the_base_and_is_cached():
    cache = fakeredis.FakeAsyncRedis(decode_responses=True)
    service = make_service(cache=cache)
    quote = await service.quote(AUCTION, Decimal("1200.00"))
    assert (quote.min_increment, quote.min_next_bid, quote.hot) == (
        Decimal("25.00"), Decimal("1225.00"), False)
    assert await cache.get(increment_cache_key(AUCTION)) == "25.00"
    assert 0 < await cache.ttl(increment_cache_key(AUCTION)) <= 60


async def test_velocity_raises_the_quote_and_flags_the_auction_hot():
    clock = Clock()
    repository = InMemoryPricingRepository()
    service = make_service(clock, repository)
    await burst(service, clock, 30)
    velocity = await service.velocity(AUCTION)
    assert velocity.bids_per_minute == 30.0 and velocity.hot
    quote = await service.quote(AUCTION, Decimal("1200.00"))
    assert quote.min_increment == Decimal("38.00") and quote.hot
    assert repository.flags[str(AUCTION)].change is Change.FLAGGED
    assert service.metrics.hot_auctions._value.get() == 1


async def test_each_accepted_bid_warms_the_fallback_for_its_amount():
    cache = fakeredis.FakeAsyncRedis(decode_responses=True)
    clock = Clock()
    service = make_service(clock, cache=cache)
    await service.on_bid_accepted(bid(1, clock.now, "600.00"))
    assert await cache.get(increment_cache_key(AUCTION)) == "10.00"


async def test_replayed_events_are_ignored():
    clock = Clock()
    service = make_service(clock)
    await service.on_bid_accepted(bid(1, clock.now))
    await service.on_bid_accepted(bid(1, clock.now))
    assert (await service.velocity(AUCTION)).bids_per_minute == 1.0


async def test_flush_persists_buckets_and_cools_quiet_auctions():
    clock = Clock()
    repository = InMemoryPricingRepository()
    service = make_service(clock, repository)
    await burst(service, clock, 30)
    await burst(service, clock, 2, auction=OTHER)
    assert await service.flush() > 0
    assert sum(b.count for b in repository.buckets.values()) == 32
    assert await service.flush() == 0  # nothing dirty
    clock.advance(120)
    await service.flush()
    assert repository.flags[str(AUCTION)].change is Change.CLEARED
    assert service.tracker.auctions() == []
    assert not (await service.velocity(AUCTION)).hot


async def test_flush_clears_a_hot_auction_whose_rate_has_dropped():
    clock = Clock()
    repository = InMemoryPricingRepository()
    service = make_service(clock, repository)
    await burst(service, clock, 30)
    clock.advance(50)  # only a few bids left in the window, but some remain
    await service.flush()
    assert repository.flags[str(AUCTION)].change is Change.CLEARED


async def test_flush_retries_buckets_when_the_database_fails():
    class Failing(InMemoryPricingRepository):
        fail = True

        async def save_buckets(self, buckets):
            if self.fail:
                raise ConnectionError("db down")
            await super().save_buckets(buckets)

    clock = Clock()
    repository = Failing()
    service = make_service(clock, repository)
    await burst(service, clock, 3)
    with pytest.raises(ConnectionError):
        await service.flush()
    repository.fail = False
    assert await service.flush() == 1


async def test_old_history_is_pruned():
    repository = InMemoryPricingRepository()
    await repository.save_buckets([StoredBucket(str(AUCTION), T0 - timedelta(days=2), 5, 3)])
    service = make_service(Clock(), repository)
    await service.flush()
    assert repository.buckets == {}


async def test_warm_up_restores_ladder_velocity_and_hot_set():
    clock = Clock()
    repository = InMemoryPricingRepository(ladder=(
        IncrementRule(Decimal("0"), None, Decimal("3.00"), Decimal("1.0")),))
    await repository.save_buckets([
        StoredBucket(str(AUCTION), T0 - timedelta(seconds=10), 5, 12),
        StoredBucket(str(AUCTION), T0 - timedelta(seconds=300), 5, 99),
    ])
    first = make_service(clock, repository)
    await burst(first, clock, 30, auction=OTHER)
    service = make_service(clock, repository)
    await service.warm_up()
    assert (await service.velocity(AUCTION)).bids_per_minute == 12.0
    assert service.hot.is_hot(str(OTHER))
    assert (await service.quote(AUCTION, Decimal("10.00"))).min_increment == Decimal("3.00")


async def test_cache_and_flag_failures_never_fail_a_quote():
    class BrokenCache:
        async def set(self, *args, **kwargs):
            raise ConnectionError("redis down")

    class BrokenFlags(InMemoryPricingRepository):
        async def record_flag(self, transition):
            raise ConnectionError("db down")

    clock = Clock()
    service = make_service(clock, BrokenFlags(), cache=BrokenCache())
    await burst(service, clock, 30)
    quote = await service.quote(AUCTION, Decimal("50.00"))
    assert quote.hot and quote.min_increment == Decimal("2.00")
