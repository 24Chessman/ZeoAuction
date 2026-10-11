"""CT-3 (Bid -> Pricing) circuit breaker and stale-increment fallback, SDD Table 2.2 (#43).

Opens after 5 failures in 10 s. While open the provider is not called, the last cached
increment is used (never below the tier floor) and the quote is flagged ``stale``. Bidding never
stops because Pricing is down, and replay still names the live winner.
"""

import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import fakeredis
import pytest

from app.adapters.circuit_breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from app.adapters.pricing_client import (
    INCREMENT_CACHE_TTL_SECONDS,
    INCREMENT_TIERS,
    HttpPricingClient,
    increment_cache_key,
    tier_increment,
)
from app.domain.conflict import replay
from app.domain.model import Leader
from tests.fakes import AUCTION_ID, FakePricing, ManualClock

LADDER_SQL = Path(__file__).resolve().parents[3] / "infra/postgres/init/51-pricing-dynamic.sql"


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


def ct3_breaker(clock: ManualClock) -> CircuitBreaker:
    return CircuitBreaker("pricing", failure_threshold=5, window_seconds=10.0,
                          reset_seconds=5.0, clock=clock)


async def test_five_failures_in_ten_seconds_open_the_breaker_and_stop_calls(redis):
    clock = ManualClock()
    pricing = FakePricing(increment="7.00")
    client = HttpPricingClient(pricing.client(), ct3_breaker(clock), redis)
    await client.quote(AUCTION_ID, Decimal("200.00"))
    pricing.failing = True
    for _ in range(5):
        quote = await client.quote(AUCTION_ID, Decimal("200.00"))
        assert quote.stale
        clock.advance(1.0)
    assert client.breaker.state == OPEN
    calls = pricing.calls
    for _ in range(20):  # bidding continues on the cached increment, provider untouched
        quote = await client.quote(AUCTION_ID, Decimal("200.00"))
        assert (quote.min_increment, quote.stale) == (Decimal("7.00"), True)
    assert pricing.calls == calls


async def test_failures_spread_over_more_than_ten_seconds_do_not_open_it(redis):
    clock = ManualClock()
    pricing = FakePricing()
    pricing.failing = True
    client = HttpPricingClient(pricing.client(), ct3_breaker(clock), redis)
    for _ in range(8):
        await client.quote(AUCTION_ID, Decimal("50.00"))
        clock.advance(3.0)
    assert client.breaker.state == CLOSED
    assert pricing.calls == 8


async def test_pricing_back_closes_the_breaker_and_clears_the_stale_flag(redis):
    clock = ManualClock()
    pricing = FakePricing(increment="9.00")
    client = HttpPricingClient(pricing.client(), ct3_breaker(clock), redis)
    pricing.failing = True
    for _ in range(5):
        await client.quote(AUCTION_ID, Decimal("200.00"))
    assert client.breaker.state == OPEN
    pricing.failing = False
    clock.advance(5.0)
    assert client.breaker.state == HALF_OPEN
    quote = await client.quote(AUCTION_ID, Decimal("200.00"))
    assert (quote.min_increment, quote.stale) == (Decimal("9.00"), False)
    assert client.breaker.state == CLOSED


async def test_a_cached_increment_from_a_lower_band_is_raised_to_the_tier(redis):
    """₹1 cached at ₹50, then the leader is at ₹600: the fallback must be at least ₹10."""
    pricing = FakePricing(increment="1.00")
    client = HttpPricingClient(pricing.client(), ct3_breaker(ManualClock()), redis)
    await client.quote(AUCTION_ID, Decimal("50.00"))
    pricing.failing = True
    quote = await client.quote(AUCTION_ID, Decimal("600.00"))
    assert (quote.min_increment, quote.min_next_bid, quote.stale) == (
        Decimal("10.00"), Decimal("610.00"), True)


async def test_the_cached_increment_expires_after_sixty_seconds(redis):
    client = HttpPricingClient(FakePricing().client(), ct3_breaker(ManualClock()), redis)
    await client.quote(AUCTION_ID, Decimal("200.00"))
    assert INCREMENT_CACHE_TTL_SECONDS == 60
    assert 0 < await redis.ttl(increment_cache_key(AUCTION_ID)) <= 60


async def test_replay_names_the_live_winner_across_a_pricing_outage(redis):
    """Bids accepted on dynamic, cached and tier increments all clear the replay's floor."""
    clock = ManualClock()
    pricing = FakePricing(increment="12.00")  # a hot auction's dynamic increment
    client = HttpPricingClient(pricing.client(), ct3_breaker(clock), redis)
    leader, accepted = Decimal("90.00"), []
    for seq in range(1, 41):
        if seq == 15:
            pricing.failing = True
        if seq == 30:
            await redis.delete(increment_cache_key(AUCTION_ID))  # cache expired mid-outage
        quote = await client.quote(AUCTION_ID, leader)
        leader = quote.min_next_bid
        accepted.append(Leader(amount=leader, server_seq=seq,
                               bid_id=UUID(int=seq), bidder_id=UUID(int=seq % 3)))
    winner = replay(reversed(accepted), Decimal("90.00"), tier_increment)
    assert winner == accepted[-1]


def test_tier_table_matches_the_pricing_ladder_floor():
    """INCREMENT_TIERS must equal the base increments of 51-pricing-dynamic.sql."""
    rows = re.findall(
        r"\(([\d.]+),\s*([\d.]+|NULL),\s*([\d.]+),\s*[\d.]+\)", LADDER_SQL.read_text())
    ladder = tuple((None if upper == "NULL" else Decimal(upper), Decimal(base))
                   for _, upper, base in rows)
    assert ladder == INCREMENT_TIERS
