"""Contended single-auction bidding harness (#22, FR-TEST-3, AC-02).

Drives a fixed rate of bids (default 200/s) at ONE auction and checks two things:

1. **Replay agrees with the live system.** The accepted-bid log (``bid.events``) is replayed
   ``--replays`` times in shuffled arrival order through the pure resolver; every replay must
   name the live leader.
2. **Identical winner across runs.** The bid schedule (bidders, amounts, timing) is generated
   from ``--seed``, so repeated runs must end with the same winning bidder and amount, however
   the requests interleave.

It also reports the achieved rate, outcome counts by code, and acknowledgement latency
percentiles: the numbers Plan 4 tunes against.

Modes:

* ``inproc`` (default): the real bid hot path (validation, Lua compare-and-set, sequencing,
  idempotency, publish) on one event loop against an in-memory Redis. No infrastructure;
  ``services/bid/tests/test_concurrency_harness.py`` runs a short version in CI.
* ``http``: real HTTP against a running bid service (the Compose stack). Mints tokens with the
  local development JWT secret and replays from ``GET /auctions/{id}/bids`` after the flusher
  catches up. Acceptance numbers come from the load-test host, not a laptop (README).

    python tests/load/concurrency_harness.py --rate 200 --duration 10 --runs 3
    python tests/load/concurrency_harness.py --mode http --base-url http://localhost:8004 \\
        --auction 00000000-0000-4000-8000-000000000201
"""

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
BID_SERVICE = ROOT / "services" / "bid"
STARTING_PRICE = Decimal("100.00")
# The seeded OPEN auction in infra/postgres/seed/dev-seed.sql and its seller.
SEED_AUCTION = UUID("00000000-0000-4000-8000-000000000201")
SEED_SELLER = UUID("00000000-0000-4000-8000-000000000002")


@dataclass(frozen=True)
class PlannedBid:
    index: int
    at: float  # seconds after the start
    bidder: UUID
    amount: Decimal


@dataclass
class Observation:
    planned: PlannedBid
    status: int
    code: str
    latency: float
    body: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    observations: list[Observation]
    elapsed: float
    winner: tuple[UUID, Decimal] | None
    replay_agrees: bool

    def summary(self) -> dict[str, Any]:
        latencies = sorted(o.latency for o in self.observations)

        def pct(p: float) -> float:
            if not latencies:
                return 0.0
            return latencies[min(len(latencies) - 1, int(p * len(latencies)))] * 1000

        return {
            "bids": len(self.observations),
            "achieved_rate": round(len(self.observations) / self.elapsed, 1),
            "outcomes": dict(Counter(o.code for o in self.observations)),
            "latency_ms": {"p50": round(pct(0.50), 2), "p95": round(pct(0.95), 2),
                           "p99": round(pct(0.99), 2),
                           "mean": round(statistics.fmean(latencies) * 1000, 2)
                           if latencies else 0.0},
            "winner": None if self.winner is None else
            {"bidder": str(self.winner[0]), "amount": str(self.winner[1])},
            "replay_agrees": self.replay_agrees,
        }


def plan_bids(seed: int, rate: float, duration: float, *, burst: int = 10,
              bidders: int = 25) -> list[PlannedBid]:
    """A contended schedule. Bids leave in bursts of ``burst`` at the same instant, so they
    race for the same compare-and-set. Each amount is the planned price plus -1 to +2 tier
    increments, so bids tie, undercut and outbid each other. The final bid is the unique
    maximum, so the winner is defined by the schedule and never by timing."""
    _, _, increment_for = _bid_imports()
    rng = random.Random(seed)
    people = [UUID(int=rng.getrandbits(128), version=4) for _ in range(bidders)]
    count = max(2, int(rate * duration))
    price = STARTING_PRICE
    plan = []
    for i in range(count - 1):
        amount = max(STARTING_PRICE, price + increment_for(price) * rng.choice((-1, 0, 1, 1, 2)))
        price = max(price, amount)
        plan.append(PlannedBid(i, (i // burst) * burst / rate, rng.choice(people), amount))
    top = price + increment_for(price) * 20
    plan.append(PlannedBid(count - 1, ((count - 1) // burst) * burst / rate,
                           rng.choice(people), top))
    return plan


def expected_winner(plan: list[PlannedBid]) -> tuple[UUID, Decimal]:
    top = max(plan, key=lambda p: p.amount)
    return top.bidder, top.amount


async def paced(plan: list[PlannedBid], fire) -> tuple[list[Observation], float]:
    """Start each bid at its planned offset; never wait for one to finish before the next."""
    loop = asyncio.get_running_loop()
    start = loop.time()

    async def one(planned: PlannedBid) -> Observation:
        delay = start + planned.at - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        began = time.perf_counter()
        status, code, body = await fire(planned)
        return Observation(planned, status, code, time.perf_counter() - began, body)

    observations = await asyncio.gather(*(one(p) for p in plan))
    return list(observations), loop.time() - start


# ---------------------------------------------------------------------- in-process mode


def _bid_imports():
    if str(BID_SERVICE) not in sys.path:
        sys.path.insert(0, str(BID_SERVICE))
    from app.adapters.pricing_client import tier_increment
    from app.domain.conflict import replay
    from app.domain.model import Leader

    return Leader, replay, tier_increment


def build_inproc_service():
    """The bid service's real hot path over in-memory infrastructure."""
    _bid_imports()
    from datetime import UTC, datetime, timedelta

    import fakeredis
    from prometheus_client import CollectorRegistry

    from app.adapters.auction_client import AuctionSnapshot
    from app.adapters.bid_repo import InMemoryBidRepository
    from app.adapters.kafka_producer import InMemoryBidEventPublisher
    from app.adapters.price_buffer import RedisPriceBuffer
    from app.adapters.pricing_client import StubPricingClient
    from app.domain.idempotency import IdempotencyGuard
    from app.service import BidMetrics, BidService

    snapshot = AuctionSnapshot(
        auction_id=SEED_AUCTION, seller_id=SEED_SELLER, state="OPEN", bid_permitted=True,
        currency="USD", starting_price=STARTING_PRICE,
        closes_at=datetime.now(UTC) + timedelta(days=1), as_of=datetime.now(UTC),
    )

    class OpenAuction:
        async def get_state(self, auction_id):
            return snapshot

    class AmpleFunds:
        async def available(self, bidder_id):
            return Decimal("10000000.00")

    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    publisher = InMemoryBidEventPublisher()
    prices = RedisPriceBuffer(redis)
    service = BidService(
        auctions=OpenAuction(), pricing=StubPricingClient(), funds=AmpleFunds(), prices=prices,
        publisher=publisher, idempotency=IdempotencyGuard(redis), bids=InMemoryBidRepository(),
        metrics=BidMetrics(CollectorRegistry()), max_resolution_attempts=50,
    )
    return service, publisher, prices


async def run_inproc(plan: list[PlannedBid], replays: int, seed: int) -> RunResult:
    Leader, replay, tier_increment = _bid_imports()
    from zeo_common import ApiError
    from zeo_common.auth import Principal

    service, publisher, prices = build_inproc_service()

    async def fire(planned: PlannedBid):
        principal = Principal(user_id=planned.bidder, role="USER", kyc_status="NOT_SUBMITTED",
                              suspended=False)
        try:
            result = await service.place_bid(principal, SEED_AUCTION, planned.amount,
                                             f"harness-{uuid4()}", None)
        except ApiError as error:
            return error.status_code, error.code, {}
        return result.status_code, "ACCEPTED", result.body

    observations, elapsed = await paced(plan, fire)
    live = await prices.leader(SEED_AUCTION)
    log = [Leader(Decimal(e["amount"]), e["server_seq"], UUID(e["bid_id"]), UUID(e["bidder_id"]))
           for e in publisher.events]
    agrees = check_replays(log, live, replays, seed, replay, tier_increment)
    winner = None if live is None else (live.bidder_id, live.amount)
    return RunResult(observations, elapsed, winner, agrees)


def check_replays(log, live, replays, seed, replay, increment_for) -> bool:
    rng = random.Random(seed)
    shuffled = list(log)
    for _ in range(replays):
        rng.shuffle(shuffled)
        if replay(shuffled, STARTING_PRICE, increment_for) != live:
            return False
    return True


# ---------------------------------------------------------------------- HTTP mode


async def run_http(plan: list[PlannedBid], replays: int, seed: int, base_url: str,
                   auction: UUID, jwt_secret: str, settle_seconds: float) -> RunResult:
    import httpx

    Leader, replay, tier_increment = _bid_imports()
    from zeo_common.auth import JwtSettings, encode_access_token

    jwt = JwtSettings(secret=jwt_secret)
    tokens = {
        bidder: encode_access_token(jwt, user_id=bidder, role="USER",
                                    kyc_status="NOT_SUBMITTED", suspended=False)
        for bidder in {p.bidder for p in plan}
    }
    limits = httpx.Limits(max_connections=400, max_keepalive_connections=400)
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0, limits=limits) as http:

        async def fire(planned: PlannedBid):
            response = await http.post(
                f"/api/v1/auctions/{auction}/bids",
                json={"amount": f"{planned.amount:.2f}"},
                headers={"Authorization": f"Bearer {tokens[planned.bidder]}",
                         "Idempotency-Key": f"harness-{uuid4()}"},
            )
            body = response.json() if response.content else {}
            code = "ACCEPTED" if response.status_code == 202 else body.get("code", "HTTP_ERROR")
            return response.status_code, code, body

        observations, elapsed = await paced(plan, fire)
        await asyncio.sleep(settle_seconds)  # let the flusher persist the tail
        log = await fetch_bid_log(http, auction)

    accepted = [o for o in observations if o.code == "ACCEPTED"]
    if not accepted:
        return RunResult(observations, elapsed, None, False)
    top = max(accepted, key=lambda o: o.body["server_seq"])
    live = Leader(Decimal(top.body["current_price"]), top.body["server_seq"],
                  UUID(top.body["bid_id"]), top.planned.bidder)
    by_bid = {o.body["bid_id"]: o.planned.bidder for o in accepted}
    log = [Leader(entry.amount, entry.server_seq, entry.bid_id,
                  by_bid.get(str(entry.bid_id), entry.bidder_id)) for entry in log]
    agrees = check_replays(log, live, replays, seed, replay, tier_increment)
    return RunResult(observations, elapsed, (live.bidder_id, live.amount), agrees)


async def fetch_bid_log(http, auction: UUID):
    Leader, _, _ = _bid_imports()
    entries = []
    page_number = 1
    while True:
        page = (await http.get(f"/api/v1/auctions/{auction}/bids",
                               params={"page": page_number, "page_size": 100})).json()
        for item in page["items"]:
            entries.append(Leader(Decimal(item["amount"]), item["server_seq"],
                                  UUID(item["bid_id"]), UUID(int=0)))
        if page_number * page["page_size"] >= page["total"]:
            return entries
        page_number += 1


# ---------------------------------------------------------------------- entry point


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=("inproc", "http"), default="inproc")
    parser.add_argument("--rate", type=float, default=200.0, help="bids per second")
    parser.add_argument("--duration", type=float, default=10.0, help="seconds")
    parser.add_argument("--runs", type=int, default=3, help="independent runs, same seed")
    parser.add_argument("--replays", type=int, default=100)
    parser.add_argument("--seed", type=int, default=22)
    parser.add_argument("--burst", type=int, default=10, help="bids sent at the same instant")
    parser.add_argument("--base-url", default="http://localhost:8004")
    parser.add_argument("--auction", type=UUID, default=SEED_AUCTION)
    parser.add_argument("--jwt-secret", default="zeo-dev-jwt-secret-not-for-production-use")
    parser.add_argument("--settle-seconds", type=float, default=3.0)
    args = parser.parse_args(argv)

    plan = plan_bids(args.seed, args.rate, args.duration, burst=args.burst)
    results = []
    for run in range(args.runs):
        if args.mode == "inproc":
            result = await run_inproc(plan, args.replays, args.seed)
        else:
            # Each HTTP run needs a fresh auction, since the price only goes up.
            result = await run_http(plan, args.replays, args.seed, args.base_url, args.auction,
                                    args.jwt_secret, args.settle_seconds)
        results.append(result)
        print(json.dumps({"run": run + 1} | result.summary()))

    winners = {r.winner for r in results}
    ok = len(winners) == 1 and all(r.replay_agrees for r in results)
    print(json.dumps({"identical_winner": len(winners) == 1,
                      "expected_winner": str(expected_winner(plan)[1]),
                      "all_replays_agree": all(r.replay_agrees for r in results),
                      "result": "PASS" if ok else "FAIL"}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
