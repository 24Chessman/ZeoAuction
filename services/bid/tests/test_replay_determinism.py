"""AC-04 forerunner (#20): equal concurrent bids resolve identically across 100 replays.

The full hot path runs N simultaneous submissions on one event loop against Redis (Lua CAS
included). The published ``bid.events`` log is then replayed 100 times in shuffled arrival
order; every replay must name the same winner as the live system. The full concurrency
harness (#22) arrives in Plan 3.
"""

import asyncio
import random
from decimal import Decimal
from uuid import UUID, uuid4

import fakeredis
import pytest
from prometheus_client import CollectorRegistry

from app.adapters.auction_client import AuctionStateClient
from app.adapters.bid_repo import InMemoryBidRepository
from app.adapters.circuit_breaker import CircuitBreaker
from app.adapters.kafka_producer import InMemoryBidEventPublisher
from app.adapters.price_buffer import RedisPriceBuffer
from app.adapters.pricing_client import StubPricingClient, tier_increment
from app.domain.conflict import replay
from app.domain.idempotency import IdempotencyGuard
from app.domain.model import Leader
from app.service import BidMetrics, BidService
from tests.fakes import AUCTION_ID, FakeFunds, FakeOrchestrator
from zeo_common import ApiError, format_money
from zeo_common.auth import Principal

STARTING = Decimal("100.00")
REPLAYS = 100


def build():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    publisher = InMemoryBidEventPublisher()
    prices = RedisPriceBuffer(redis)
    service = BidService(
        auctions=AuctionStateClient(FakeOrchestrator().client(), CircuitBreaker("ct1")),
        pricing=StubPricingClient(),
        funds=FakeFunds(),
        prices=prices,
        publisher=publisher,
        idempotency=IdempotencyGuard(redis),
        bids=InMemoryBidRepository(),
        metrics=BidMetrics(CollectorRegistry()),
    )
    return service, publisher, prices


def principal() -> Principal:
    return Principal(user_id=uuid4(), role="USER", kyc_status="NOT_SUBMITTED", suspended=False)


async def fire(service, amounts):
    async def one(amount):
        try:
            return await service.place_bid(principal(), AUCTION_ID, Decimal(amount),
                                           f"key-{uuid4()}", None)
        except ApiError as error:
            return error

    return await asyncio.gather(*(one(a) for a in amounts))


def log_of(publisher) -> list[Leader]:
    return [
        Leader(Decimal(e["amount"]), e["server_seq"], UUID(e["bid_id"]), UUID(e["bidder_id"]))
        for e in publisher.events
    ]


def assert_replays_agree(publisher, live: Leader, seed: int) -> None:
    rng = random.Random(seed)
    log = log_of(publisher)
    for _ in range(REPLAYS):
        rng.shuffle(log)
        assert replay(log, STARTING, tier_increment) == live


@pytest.mark.parametrize("n", [2, 10, 50])
async def test_equal_simultaneous_bids_have_one_winner_and_replay_agrees(n):
    service, publisher, prices = build()
    outcomes = await fire(service, ["100.00"] * n)
    accepted = [o for o in outcomes if not isinstance(o, ApiError)]
    rejected = [o for o in outcomes if isinstance(o, ApiError)]
    assert len(accepted) == 1
    assert {r.code for r in rejected} == {"BID_BELOW_INCREMENT"}
    live = await prices.leader(AUCTION_ID)
    assert str(live.bid_id) == accepted[0].body["bid_id"]
    assert_replays_agree(publisher, live, seed=n)


async def test_one_hundred_independent_runs_each_agree_with_their_replay():
    for run in range(REPLAYS):
        service, publisher, prices = build()
        await fire(service, ["100.00"] * 8)
        live = await prices.leader(AUCTION_ID)
        assert len(publisher.events) == 1
        assert replay(log_of(publisher), STARTING, tier_increment) == live, f"run {run}"


async def test_a_mixed_bidding_war_replays_to_the_live_winner():
    rng = random.Random(2026)
    service, publisher, prices = build()
    for _ in range(20):  # waves of simultaneous bids around a rising price
        leader = await prices.leader(AUCTION_ID)
        base = leader.amount if leader else STARTING
        wave = [format_money(base + rng.randint(0, 12)) for _ in range(rng.randint(2, 6))]
        await fire(service, wave)
    live = await prices.leader(AUCTION_ID)
    seqs = [e["server_seq"] for e in publisher.events]
    in_order = sorted(publisher.events, key=lambda e: e["server_seq"])
    amounts = [Decimal(e["amount"]) for e in in_order]
    assert len(seqs) == len(set(seqs))
    assert amounts == sorted(amounts)
    assert_replays_agree(publisher, live, seed=7)
