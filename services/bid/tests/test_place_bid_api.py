import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.adapters.auction_client import AuctionStateClient
from app.adapters.bid_repo import InMemoryBidRepository, StoredBid
from app.adapters.circuit_breaker import CircuitBreaker
from app.adapters.kafka_producer import InMemoryBidEventPublisher
from app.adapters.price_buffer import FLUSH_PENDING_KEY, RedisPriceBuffer, seq_key
from app.adapters.pricing_client import HttpPricingClient, StubPricingClient
from app.domain.idempotency import IdempotencyGuard
from app.main import BidDependencies, build_app
from app.service import BidService
from app.settings import Settings
from tests.fakes import AUCTION_ID, SELLER_ID, FakeAuction, FakeFunds, FakeOrchestrator, FakePricing
from zeo_common.auth import JwtSettings, encode_access_token
from zeo_common.contract_testing import assert_matches_contract

JWT = JwtSettings(secret="bid-service-test-secret-32-bytes!!")
BID_CONTRACT = "openapi/bid-service.v1.yaml"
DRAFT_AUCTION = uuid4()
CLOSED_BY_TIME = uuid4()
ALICE = UUID("00000000-0000-4000-8000-000000000004")
BOB = UUID("00000000-0000-4000-8000-000000000005")
POOR = uuid4()


def settings() -> Settings:
    env = Settings.from_env()
    return Settings(**{**env.__dict__, "alias_secret": "test-alias-secret"})


@dataclass
class Env:
    client: TestClient
    redis: fakeredis.FakeAsyncRedis
    orchestrator: FakeOrchestrator
    publisher: InMemoryBidEventPublisher
    bids: InMemoryBidRepository
    pricing: FakePricing

    def headers(self, user=ALICE, key=None, **claims):
        token = encode_access_token(
            JWT, user_id=user, role=claims.get("role", "USER"),
            kyc_status=claims.get("kyc_status", "NOT_SUBMITTED"),
            suspended=claims.get("suspended", False),
        )
        return {"Authorization": f"Bearer {token}", "Idempotency-Key": key or f"key-{uuid4()}"}

    def bid(self, amount, auction=AUCTION_ID, **kwargs):
        body = kwargs.pop("body", {"amount": amount})
        return self.client.post(f"/api/v1/auctions/{auction}/bids", json=body,
                                headers=self.headers(**kwargs))


def make_env(pricing_mode="stub") -> Env:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    orchestrator = FakeOrchestrator(
        FakeAuction(),
        FakeAuction(auction_id=DRAFT_AUCTION, state="DRAFT"),
        FakeAuction(auction_id=CLOSED_BY_TIME, closes_at=datetime.now(UTC) - timedelta(seconds=1)),
    )
    publisher = InMemoryBidEventPublisher()
    bids = InMemoryBidRepository()
    fake_pricing = FakePricing(increment="5.00")

    def dependencies(metrics):
        breaker = CircuitBreaker("auction-state")
        pricing = (
            HttpPricingClient(fake_pricing.client(), CircuitBreaker("pricing"), redis)
            if pricing_mode == "http" else StubPricingClient()
        )
        service = BidService(
            auctions=AuctionStateClient(orchestrator.client(), breaker),
            pricing=pricing,
            funds=FakeFunds(per_bidder={POOR: "50.00"}),
            prices=RedisPriceBuffer(redis),
            publisher=publisher,
            idempotency=IdempotencyGuard(redis),
            bids=bids,
            metrics=metrics,
        )
        return BidDependencies(service=service, bids=bids)

    app = build_app(settings(), dependencies=dependencies, jwt_settings=JWT)
    client = TestClient(app, raise_server_exceptions=False)
    return Env(client, redis, orchestrator, publisher, bids, fake_pricing)


@pytest.fixture
def env():
    environment = make_env()
    with environment.client:
        yield environment


async def nothing_changed(env: Env) -> None:
    assert env.publisher.events == []
    assert await env.redis.exists(f"price:{AUCTION_ID}") == 0
    assert await env.redis.get(seq_key(AUCTION_ID)) is None
    assert await env.redis.llen(FLUSH_PENDING_KEY) == 0


# ------------------------------------------------------------------------------ acceptance


def test_accepted_bid_returns_202_with_seq_and_prices(env):
    response = env.bid("100.00")
    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["server_seq"], body["current_price"], body["min_next_bid"]) == (
        1, "100.00", "105.00")
    assert_matches_contract(body, BID_CONTRACT, "/components/schemas/BidAccepted")


async def test_accepted_bid_is_published_and_queued_for_the_flusher(env):
    body = env.bid("100.00", body={"amount": "100.00", "device_fingerprint": "fp_1"}).json()
    (event,) = env.publisher.events
    assert_matches_contract(event, "events/bid_accepted.v1.json")
    assert (event["bid_id"], event["server_seq"], event["seller_id"]) == (
        body["bid_id"], 1, str(SELLER_ID))
    assert event["device_fingerprint"] == "fp_1"
    (queued,) = await env.redis.lrange(FLUSH_PENDING_KEY, 0, -1)
    assert json.loads(queued)["event"] == event


def test_sequence_increases_and_minimum_follows_the_price(env):
    assert env.bid("100.00").json()["server_seq"] == 1
    second = env.bid("105.00", user=BOB).json()
    assert (second["server_seq"], second["min_next_bid"]) == (2, "110.00")


# ------------------------------------------------------------------------------ rejections


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"suspended": True}, 403, "ACCOUNT_SUSPENDED"),
        ({"user": SELLER_ID}, 403, "SELF_BIDDING_FORBIDDEN"),
        ({"auction": DRAFT_AUCTION}, 409, "AUCTION_NOT_OPEN"),
        ({"amount": "99.99"}, 422, "BID_BELOW_INCREMENT"),
        ({"user": POOR}, 402, "INSUFFICIENT_FUNDS"),
        ({"auction": CLOSED_BY_TIME}, 409, "AUCTION_CLOSED"),
    ],
)
async def test_each_rule_rejects_with_its_code_before_any_state_change(env, kwargs, status, code):
    amount = kwargs.pop("amount", "100.00")
    response = env.bid(amount, **kwargs)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert_matches_contract(response.json(), "openapi/common.v1.yaml", "/components/schemas/Error")
    await nothing_changed(env)


def test_below_increment_reports_the_minimum(env):
    env.bid("100.00")
    response = env.bid("104.99", user=BOB)
    assert response.json()["details"] == {"min_next_bid": "105.00"}


def test_unknown_auction_is_404(env):
    assert env.bid("100.00", auction=uuid4()).status_code == 404


def test_missing_token_is_401(env):
    response = env.client.post(f"/api/v1/auctions/{AUCTION_ID}/bids", json={"amount": "100.00"},
                               headers={"Idempotency-Key": "key-12345678"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "body", [{"amount": 100.0}, {"amount": "100"}, {"amount": "100.00", "extra": 1}, {}]
)
def test_malformed_body_is_a_validation_error(env, body):
    response = env.bid("x", body=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("key", ["short", "k" * 81])
def test_idempotency_key_length_is_enforced(env, key):
    assert env.bid("100.00", key=key).status_code == 422


def test_missing_idempotency_key_is_a_validation_error(env):
    headers = env.headers()
    del headers["Idempotency-Key"]
    response = env.client.post(f"/api/v1/auctions/{AUCTION_ID}/bids", json={"amount": "100.00"},
                               headers=headers)
    assert response.status_code == 422


# ------------------------------------------------------------------------------ idempotency


def test_retry_returns_the_original_acceptance_and_creates_nothing_new(env):
    first = env.bid("100.00", key="retry-key-0001")
    retry = env.bid("100.00", key="retry-key-0001")
    assert (first.status_code, retry.status_code) == (202, 200)
    assert retry.headers["Idempotent-Replay"] == "true"
    assert retry.json() == first.json()
    assert len(env.publisher.events) == 1


def test_retry_of_a_rejection_returns_the_original_rejection(env):
    first = env.bid("99.00", key="retry-key-0002")
    retry = env.bid("500.00", key="retry-key-0002")
    assert (first.status_code, retry.status_code) == (422, 422)
    assert retry.json()["code"] == "BID_BELOW_INCREMENT"
    assert retry.headers["Idempotent-Replay"] == "true"
    assert env.publisher.events == []


def test_another_users_key_is_refused(env):
    env.bid("100.00", key="shared-key-0001")
    response = env.bid("200.00", key="shared-key-0001", user=BOB)
    assert response.status_code == 409
    assert "bid_id" not in response.text


def test_persisted_bid_answers_a_retry_after_redis_forgot_the_key(env):
    bid = StoredBid(uuid4(), AUCTION_ID, ALICE, Decimal("150.00"), 9, datetime.now(UTC),
                    "old-key-00001")
    env.bids.add(bid)
    response = env.bid("150.00", key="old-key-00001")
    assert response.status_code == 200
    assert response.json()["bid_id"] == str(bid.bid_id)
    assert response.headers["Idempotent-Replay"] == "true"
    assert env.publisher.events == []


def test_persisted_bid_of_another_user_is_not_revealed(env):
    env.bids.add(StoredBid(uuid4(), AUCTION_ID, BOB, Decimal("150.00"), 9, datetime.now(UTC),
                           "old-key-00002"))
    assert env.bid("150.00", key="old-key-00002").status_code == 409


# ------------------------------------------------------------------------------ dependencies


async def test_orchestrator_down_is_503_and_the_key_is_released(env):
    env.orchestrator.failing = True
    response = env.bid("100.00", key="outage-key-0001")
    assert response.status_code == 503
    assert response.json()["code"] == "AUCTION_STATE_UNAVAILABLE"
    await nothing_changed(env)
    env.orchestrator.failing = False
    assert env.bid("100.00", key="outage-key-0001").status_code == 202


async def test_publish_failure_rolls_back_and_is_not_acknowledged(env):
    env.bid("100.00")
    env.publisher.fail_next = True
    response = env.bid("105.00", user=BOB, key="broker-key-0001")
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    leader = await env.redis.hgetall(f"price:{AUCTION_ID}")
    assert leader["amount"] == "100.00"
    assert await env.redis.llen(FLUSH_PENDING_KEY) == 1
    retry = env.bid("105.00", user=BOB, key="broker-key-0001")
    assert retry.status_code == 202
    assert retry.json()["server_seq"] == 3  # seq 2 was burnt by the failed publish


def test_stale_increment_is_flagged_on_the_event():
    environment = make_env(pricing_mode="http")
    with environment.client:
        environment.bid("100.00")
        environment.pricing.failing = True
        assert environment.bid("120.00", user=BOB).status_code == 202
    assert [e["increment_stale"] for e in environment.publisher.events] == [False, True]


# ------------------------------------------------------------------------------ reads


def add_bid(env, auction=AUCTION_ID, bidder=ALICE, seq=1, amount="100.00"):
    bid = StoredBid(uuid4(), auction, bidder, Decimal(amount), seq, datetime.now(UTC),
                    f"k-{uuid4()}")
    env.bids.add(bid)
    return bid


def test_history_is_newest_first_with_stable_aliases(env):
    add_bid(env, seq=1)
    add_bid(env, bidder=BOB, seq=2, amount="105.00")
    add_bid(env, seq=3, amount="110.00")
    response = env.client.get(f"/api/v1/auctions/{AUCTION_ID}/bids")
    assert response.status_code == 200
    page = response.json()
    assert_matches_contract(page, BID_CONTRACT, "/components/schemas/BidPage")
    assert [b["server_seq"] for b in page["items"]] == [3, 2, 1]
    aliases = [b["bidder_alias"] for b in page["items"]]
    assert aliases[0] == aliases[2] != aliases[1]
    assert str(ALICE) not in response.text


def test_history_pages(env):
    for seq in range(1, 6):
        add_bid(env, seq=seq, amount=f"{100 + seq}.00")
    page = env.client.get(f"/api/v1/auctions/{AUCTION_ID}/bids",
                          params={"page": 2, "page_size": 2}).json()
    assert (page["total"], [b["server_seq"] for b in page["items"]]) == (5, [3, 2])


def test_history_of_unknown_auction_is_404(env):
    assert env.client.get(f"/api/v1/auctions/{uuid4()}/bids").status_code == 404


def test_history_stays_readable_while_the_orchestrator_is_down(env):
    add_bid(env)
    env.orchestrator.failing = True
    assert env.client.get(f"/api/v1/auctions/{AUCTION_ID}/bids").json()["total"] == 1


def test_get_own_bid_but_not_someone_elses(env):
    mine, theirs = add_bid(env), add_bid(env, bidder=BOB, seq=2)
    headers = {"Authorization": env.headers()["Authorization"]}
    own = env.client.get(f"/api/v1/bids/{mine.bid_id}", headers=headers)
    assert own.status_code == 200
    assert_matches_contract(own.json(), BID_CONTRACT, "/components/schemas/Bid")
    assert env.client.get(f"/api/v1/bids/{theirs.bid_id}", headers=headers).status_code == 404
    assert env.client.get(f"/api/v1/bids/{mine.bid_id}").status_code == 401


def test_ack_latency_is_recorded_for_accepted_bids(env):
    env.bid("100.00")
    env.bid("1.00", user=BOB)
    metrics = env.client.get("/metrics").text
    assert "bid_ack_latency_seconds_count 1.0" in metrics
    assert "bids_accepted_total 1.0" in metrics
    assert 'bids_rejected_total{code="BID_BELOW_INCREMENT"} 1.0' in metrics
