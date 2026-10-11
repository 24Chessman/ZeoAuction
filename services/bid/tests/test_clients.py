from decimal import Decimal
from uuid import uuid4

import fakeredis
import pytest

from app.adapters.auction_client import (
    AuctionNotFound,
    AuctionStateClient,
    AuctionStateUnavailable,
)
from app.adapters.circuit_breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker, CircuitOpen
from app.adapters.pricing_client import (
    HttpPricingClient,
    StubPricingClient,
    increment_cache_key,
    tier_increment,
)
from tests.fakes import (
    AUCTION_ID,
    SELLER_ID,
    FakeAuction,
    FakeOrchestrator,
    FakePricing,
    ManualClock,
)


def breaker(clock):
    return CircuitBreaker("test", failure_threshold=5, window_seconds=10, reset_seconds=5,
                          clock=clock)


# --------------------------------------------------------------------------- circuit breaker


async def failing():
    raise ConnectionError("down")


async def succeeding():
    return "ok"


async def test_breaker_opens_after_five_failures_in_ten_seconds():
    clock = ManualClock()
    cb = breaker(clock)
    for _ in range(4):
        with pytest.raises(ConnectionError):
            await cb.call(failing)
    assert cb.state == CLOSED
    with pytest.raises(ConnectionError):
        await cb.call(failing)
    assert cb.state == OPEN
    with pytest.raises(CircuitOpen):
        await cb.call(succeeding)


async def test_failures_outside_the_window_do_not_count():
    clock = ManualClock()
    cb = breaker(clock)
    for _ in range(4):
        with pytest.raises(ConnectionError):
            await cb.call(failing)
        clock.advance(3)
    with pytest.raises(ConnectionError):
        await cb.call(failing)
    assert cb.state == CLOSED


async def test_successes_do_not_hide_an_unhealthy_dependency():
    cb = breaker(ManualClock())
    for _ in range(5):
        await cb.call(succeeding)
        with pytest.raises(ConnectionError):
            await cb.call(failing)
    assert cb.state == OPEN


async def test_half_open_trial_success_closes_the_breaker():
    clock = ManualClock()
    cb = breaker(clock)
    for _ in range(5):
        with pytest.raises(ConnectionError):
            await cb.call(failing)
    clock.advance(5)
    assert cb.state == HALF_OPEN
    assert await cb.call(succeeding) == "ok"
    assert cb.state == CLOSED


async def test_half_open_trial_failure_reopens_the_breaker():
    clock = ManualClock()
    cb = breaker(clock)
    for _ in range(5):
        with pytest.raises(ConnectionError):
            await cb.call(failing)
    clock.advance(5)
    with pytest.raises(ConnectionError):
        await cb.call(failing)
    assert cb.state == OPEN


# --------------------------------------------------------------------------- CT-1 client


@pytest.fixture
def orchestrator():
    return FakeOrchestrator(FakeAuction(), FakeAuction(auction_id=uuid4(), state="DRAFT"))


def auction_client(orchestrator, clock):
    return AuctionStateClient(orchestrator.client(), breaker(clock), cache_seconds=2.0,
                              clock=clock)


async def test_ct1_snapshot_is_parsed(orchestrator):
    snapshot = await auction_client(orchestrator, ManualClock()).get_state(AUCTION_ID)
    assert snapshot.seller_id == SELLER_ID
    assert snapshot.bid_permitted is True
    assert snapshot.starting_price == Decimal("100.00")


async def test_ct1_unknown_auction_is_not_a_dependency_failure(orchestrator):
    clock = ManualClock()
    client = auction_client(orchestrator, clock)
    for _ in range(10):
        with pytest.raises(AuctionNotFound):
            await client.get_state(uuid4())
    assert client.breaker.state == CLOSED


async def test_ct1_falls_back_to_state_under_two_seconds_old(orchestrator):
    clock = ManualClock()
    client = auction_client(orchestrator, clock)
    fresh = await client.get_state(AUCTION_ID)
    orchestrator.failing = True
    clock.advance(1.5)
    assert await client.get_state(AUCTION_ID) == fresh


async def test_ct1_refuses_when_cached_state_is_too_old(orchestrator):
    clock = ManualClock()
    client = auction_client(orchestrator, clock)
    await client.get_state(AUCTION_ID)
    orchestrator.failing = True
    clock.advance(2.5)
    with pytest.raises(AuctionStateUnavailable):
        await client.get_state(AUCTION_ID)


async def test_ct1_refuses_with_no_cache(orchestrator):
    orchestrator.failing = True
    with pytest.raises(AuctionStateUnavailable):
        await auction_client(orchestrator, ManualClock()).get_state(AUCTION_ID)


async def test_ct1_open_breaker_stops_calling_the_provider(orchestrator):
    clock = ManualClock()
    client = auction_client(orchestrator, clock)
    orchestrator.failing = True
    for _ in range(5):
        with pytest.raises(AuctionStateUnavailable):
            await client.get_state(AUCTION_ID)
    calls = orchestrator.calls
    with pytest.raises(AuctionStateUnavailable):
        await client.get_state(AUCTION_ID)
    assert orchestrator.calls == calls


# --------------------------------------------------------------------------- CT-3 clients


@pytest.mark.parametrize(
    ("price", "increment"),
    [("0.00", "1.00"), ("99.99", "1.00"), ("100.00", "5.00"), ("999.99", "10.00"),
     ("1000.00", "25.00"), ("5000.00", "50.00"), ("9999999.00", "50.00")],
)
def test_tier_table(price, increment):
    assert tier_increment(Decimal(price)) == Decimal(increment)


async def test_stub_answers_with_the_contract_shape():
    quote = await StubPricingClient().quote(AUCTION_ID, Decimal("120.00"))
    assert quote.min_increment == Decimal("5.00")
    assert quote.min_next_bid == Decimal("125.00")
    assert quote.stale is False


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


async def test_http_pricing_quote_is_cached_for_the_fallback(redis):
    pricing = FakePricing(increment="7.00")
    client = HttpPricingClient(pricing.client(), breaker(ManualClock()), redis)
    quote = await client.quote(AUCTION_ID, Decimal("200.00"))
    assert (quote.min_increment, quote.min_next_bid, quote.stale) == (
        Decimal("7.00"), Decimal("207.00"), False)
    assert await redis.get(increment_cache_key(AUCTION_ID)) == "7.00"


async def test_http_pricing_falls_back_to_cached_increment_and_flags_stale(redis):
    pricing = FakePricing(increment="7.00")
    client = HttpPricingClient(pricing.client(), breaker(ManualClock()), redis)
    await client.quote(AUCTION_ID, Decimal("200.00"))
    pricing.failing = True
    quote = await client.quote(AUCTION_ID, Decimal("300.00"))
    assert (quote.min_increment, quote.min_next_bid, quote.stale) == (
        Decimal("7.00"), Decimal("307.00"), True)


async def test_http_pricing_without_cache_uses_the_tier_table(redis):
    pricing = FakePricing()
    pricing.failing = True
    client = HttpPricingClient(pricing.client(), breaker(ManualClock()), redis)
    quote = await client.quote(AUCTION_ID, Decimal("50.00"))
    assert (quote.min_increment, quote.stale) == (Decimal("1.00"), True)
