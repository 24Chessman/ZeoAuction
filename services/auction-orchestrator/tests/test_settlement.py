"""Settlement hand-off (#33): CLOSED with a winner -> Payment opens the order (S1, CT-4) ->
HELD on payment.events -> A7 settle. Losing bidders are never sent to Payment (AC-09)."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from prometheus_client import CollectorRegistry

from app.adapters.auction_repo import InMemoryAuctionRepository, StaleAuction
from app.adapters.bid_events import parse_accepted
from app.adapters.kafka_producer import InMemoryAuctionEventPublisher
from app.adapters.payment_client import (
    PaymentClient,
    PaymentUnavailable,
    SettlementRefused,
    payment_breaker,
)
from app.adapters.payment_events import PaymentEventsConsumer, SettlementStep, decode
from app.domain.anti_snipe import AcceptedBid, apply_bid
from app.domain.settlement import NotSettleable, settlement_request
from app.service import AuctionMetrics, AuctionService
from tests.support import NOW, SELLER, draft
from zeo_common.contract_testing import assert_matches_contract

WINNER = UUID("00000000-0000-4000-8000-000000000003")
LOSER = UUID("00000000-0000-4000-8000-000000000004")
TOKEN = "orchestrator-test-internal-token"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class FakePayment:
    """Records CT-4 requests; answers with one order per auction, or fails as scripted."""

    def __init__(self, fail: int = 0, status: int = 201):
        self.requests: list[tuple[dict, dict]] = []
        self.fail = fail
        self.status = status
        self.orders: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((body, dict(request.headers)))
        if self.fail:
            self.fail -= 1
            return httpx.Response(503, json={"code": "SERVICE_UNAVAILABLE"})
        if self.status >= 400:
            return httpx.Response(self.status, json={"code": "SETTLEMENT_CONFLICT",
                                                     "message": "different winner"})
        order_id = self.orders.setdefault(body["auction_id"], str(uuid4()))
        return httpx.Response(self.status, json={"order_id": order_id, "state": "INVOICED"})


def client(fake: FakePayment, clock=None) -> PaymentClient:
    http = httpx.AsyncClient(base_url="http://payment", transport=httpx.MockTransport(
        fake.handler))
    breaker = payment_breaker(clock=lambda: clock.now.timestamp()) if clock else payment_breaker()
    return PaymentClient(http, breaker, TOKEN)


def service(fake: FakePayment | None = None, clock=None):
    clock = clock or Clock()
    repo = InMemoryAuctionRepository()
    svc = AuctionService(repo, InMemoryAuctionEventPublisher(),
                         AuctionMetrics(CollectorRegistry()), clock=clock,
                         payment=client(fake, clock) if fake else None)
    return svc, repo, clock


def closed_auction(amount="1250.00", **overrides):
    """An auction drained with WINNER leading after LOSER was outbid."""
    auction = replace(draft(currency="INR"), state="OPEN")
    first = AcceptedBid(auction.id, uuid4(), 1, NOW, bidder_id=LOSER, amount=Decimal("1200.00"))
    second = AcceptedBid(auction.id, uuid4(), 2, NOW, bidder_id=WINNER, amount=Decimal(amount))
    auction = apply_bid(apply_bid(auction, first, NOW).auction, second, NOW).auction
    return replace(auction, **({"state": "CLOSED", "winning_bid_id": auction.leading_bid_id}
                               | overrides))


# ---------------------------------------------------------------------- the winner


def test_bid_events_carry_the_bidder_and_amount():
    bid = parse_accepted({
        "schema_version": 1, "auction_id": str(uuid4()), "bid_id": str(uuid4()),
        "bidder_id": str(WINNER), "amount": "1250.00", "server_seq": 3,
        "accepted_at": "2026-10-10T12:00:00Z",
    })
    assert (bid.bidder_id, bid.amount) == (WINNER, Decimal("1250.00"))
    assert parse_accepted({"schema_version": 1, "auction_id": str(uuid4()),
                           "bid_id": str(uuid4()), "server_seq": 1,
                           "accepted_at": "2026-10-10T12:00:00Z", "amount": 12.5}) is None


def test_only_the_winner_is_sent_for_settlement():
    request = settlement_request(closed_auction())
    assert (request.buyer_id, request.seller_id, request.winning_bid_amount, request.currency) == (
        WINNER, SELLER, Decimal("1250.00"), "INR")
    assert request.idempotency_key.endswith(":settle")


@pytest.mark.parametrize("overrides", [
    {"state": "SETTLED"}, {"winning_bid_id": None}, {"settlement_order_id": uuid4()},
    {"leading_bidder_id": None},
])
def test_only_closed_unsettled_winners_are_settleable(overrides):
    with pytest.raises(NotSettleable):
        settlement_request(closed_auction(**overrides))


# ---------------------------------------------------------------------- S1 via CT-4


async def test_the_timer_opens_the_order_once():
    fake = FakePayment()
    svc, repo, _ = service(fake)
    auction = closed_auction()
    await repo.add(auction)
    assert await svc.tick() == [(auction.id, "invoice")]
    stored = await repo.get(auction.id)
    assert str(stored.settlement_order_id) == fake.orders[str(auction.id)]
    assert stored.state == "CLOSED"  # A7 waits for HELD
    assert await svc.tick() == []
    body, headers = fake.requests[0]
    assert_matches_contract(body, "openapi/internal/settlement.v1.yaml",
                            "/components/schemas/SettlementRequest")
    assert body["buyer_id"] == str(WINNER) and body["winning_bid_amount"] == "1250.00"
    assert headers["idempotency-key"] == f"auction:{auction.id}:settle"
    assert headers["x-internal-token"] == TOKEN
    assert len(fake.requests) == 1


async def test_payment_down_defers_settlement_and_the_breaker_stops_the_pass():
    fake = FakePayment(fail=10)
    svc, repo, clock = service(fake)
    auctions = [closed_auction() for _ in range(2)]
    for auction in auctions:
        await repo.add(auction)
    for _ in range(4):
        assert await svc.settle_pending() == []
    assert len(fake.requests) == 3  # the breaker opened after three failures
    assert [(await repo.get(a.id)).state for a in auctions] == ["CLOSED", "CLOSED"]

    fake.fail = 0
    clock.now += timedelta(seconds=11)  # breaker half-open: one trial, then closed
    assert sorted(await svc.settle_pending()) == sorted(a.id for a in auctions)
    keys = {headers["idempotency-key"] for _, headers in fake.requests}
    assert keys == {f"auction:{a.id}:settle" for a in auctions}


async def test_a_refusal_skips_that_auction_only():
    svc, repo, _ = service(FakePayment(status=409))
    await repo.add(closed_auction())
    assert await svc.settle_pending() == []


async def test_without_payment_wiring_nothing_is_sent():
    svc, repo, _ = service(None)
    await repo.add(closed_auction())
    assert await svc.settle_pending() == []


async def test_auctions_without_a_winner_are_never_invoiced():
    fake = FakePayment()
    svc, repo, _ = service(fake)
    await repo.add(replace(draft(), state="CLOSED"))
    assert await svc.settle_pending() == [] and fake.requests == []


async def test_a_lost_race_is_retried_next_pass():
    fake = FakePayment()
    svc, repo, _ = service(fake)
    auction = closed_auction()
    await repo.add(auction)

    async def stale(before, after):
        raise StaleAuction(str(before.id))

    repo.record_settlement = stale
    assert await svc.settle_pending() == []


# ---------------------------------------------------------------------- A7 on HELD


async def test_held_settles_the_auction_once():
    fake = FakePayment()
    svc, repo, _ = service(fake)
    auction = closed_auction()
    await repo.add(auction)
    await svc.settle_pending()
    order_id = UUID(fake.orders[str(auction.id)])
    step = SettlementStep(auction.id, order_id, "HELD")
    assert await svc.on_settlement_step(step) is True
    assert (await repo.get(auction.id)).state == "SETTLED"
    assert svc.publisher.events[-1]["event"] == "settle"
    assert await svc.on_settlement_step(step) is False  # redelivery
    assert repo.lifecycle(auction.id).count("settle") == 1


async def test_held_before_our_own_record_still_settles():
    svc, repo, _ = service(FakePayment())
    auction = closed_auction()
    await repo.add(auction)
    order_id = uuid4()
    assert await svc.on_settlement_step(SettlementStep(auction.id, order_id, "HELD"))
    stored = await repo.get(auction.id)
    assert (stored.state, stored.settlement_order_id) == ("SETTLED", order_id)


@pytest.mark.parametrize("step_type", ["INVOICED", "CAPTURED", "COMPENSATED"])
async def test_other_steps_do_not_settle(step_type):
    svc, repo, _ = service(FakePayment())
    auction = closed_auction()
    await repo.add(auction)
    assert not await svc.on_settlement_step(SettlementStep(auction.id, uuid4(), step_type))
    assert not await svc.on_settlement_step(SettlementStep(uuid4(), uuid4(), "HELD"))
    assert (await repo.get(auction.id)).state == "CLOSED"


# ---------------------------------------------------------------------- adapters


async def test_payment_client_maps_answers():
    request = settlement_request(closed_auction())
    assert isinstance(await client(FakePayment()).open_order(request), UUID)
    with pytest.raises(SettlementRefused):
        await client(FakePayment(status=422)).open_order(request)
    with pytest.raises(PaymentUnavailable):
        await client(FakePayment(fail=1)).open_order(request)
    broken = PaymentClient(httpx.AsyncClient(base_url="http://payment", transport=(
        httpx.MockTransport(lambda _r: httpx.Response(201, json={})))), payment_breaker(), TOKEN)
    with pytest.raises(PaymentUnavailable):
        await broken.open_order(request)


def step_bytes(**overrides) -> bytes:
    event = {"schema_version": 1, "auction_id": str(uuid4()), "order_id": str(uuid4()),
             "type": "HELD"} | overrides
    return json.dumps(event).encode()


def test_decode_skips_unknown_versions_and_garbage():
    assert decode(step_bytes()).type == "HELD"
    for value in (step_bytes(schema_version=2), b"not json", b"[]", step_bytes(order_id="x")):
        assert decode(value) is None


class FakeConsumer:
    def __init__(self, values):
        self.values = values
        self.commits = 0
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def commit(self):
        self.commits += 1

    def __aiter__(self):
        async def messages():
            for value in self.values:
                yield type("Message", (), {"value": value})()
        return messages()


async def test_consumer_commits_after_handling_and_retries_failures():
    seen, failures = [], [1]

    async def handler(step):
        if failures:
            failures.pop()
            raise RuntimeError("database down")
        seen.append(step.type)

    async def no_sleep(_):
        return None

    fake = FakeConsumer([step_bytes(), b"garbage", step_bytes(type="CAPTURED")])
    await PaymentEventsConsumer(fake, handler, sleep=no_sleep).run()
    assert seen == ["HELD", "CAPTURED"]
    assert fake.commits == 3 and fake.started and fake.stopped
