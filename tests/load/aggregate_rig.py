"""Aggregate load rig: many auctions at once, toward 1000 bids/s across 50 auctions (#23).

Where ``concurrency_harness.py`` hammers ONE auction to prove determinism, this rig spreads an
aggregate rate over ``--auctions`` auctions (each one contended in bursts) and reports what the
week-9 baseline needs:

* acknowledgement latency p50/p95/p99 against the 500 ms budget;
* in-process mode only: the same percentiles **per budget segment** of SDD Table 9.3, by timing
  every call the hot path makes through its injected adapters:

  ===================  ==========  ===============================================
  segment              budget ms   calls timed
  ===================  ==========  ===============================================
  idempotency          10          ``IdempotencyGuard.claim/complete``
  validation           180         auction state (CT-1), leader read, CT-3, funds
  sequencing_cas       20          ``next_seq`` + ``compare_and_set`` (all rounds)
  enqueue_publish      60          ``bid.events`` publish + flusher enqueue
  other                -           everything else in-process (domain logic, JSON)
  ===================  ==========  ===============================================

  Gateway (40), response (40) and network only exist in HTTP mode;
* per auction, that replaying its accepted log names its live leader (AC-04 holds under load);
* a rate sweep (``--sweep 250,500,1000``) for the latency-vs-load curve.

    python tests/load/aggregate_rig.py --rate 1000 --auctions 50 --duration 10
    python tests/load/aggregate_rig.py --sweep 250,500,1000,1500 --duration 5 --markdown
    python tests/load/aggregate_rig.py --mode http --base-url http://localhost:8004 \\
        --auction-ids ids.txt --rate 200 --duration 10

In-process numbers measure the hot path's logic over in-memory Redis on one event loop; they
are indicative only. Acceptance numbers come from the dedicated 8 vCPU / 16 GB host in HTTP
mode (docs/architecture.md section 4; infra/loadtest/README.md).
"""

import argparse
import asyncio
import contextvars
import json
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from concurrency_harness import STARTING_PRICE, _bid_imports, check_replays  # noqa: E402

SEGMENTS = ("idempotency", "validation", "sequencing_cas", "enqueue_publish")
BUDGET_MS = {"gateway": 40, "idempotency": 10, "validation": 180, "sequencing_cas": 20,
             "enqueue_publish": 60, "response": 40, "headroom": 150, "total": 500}
SELLER = UUID("00000000-0000-4000-8000-000000000002")

_timings: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "timings", default=None)


@dataclass(frozen=True)
class PlannedBid:
    at: float
    auction: UUID
    bidder: UUID
    amount: Decimal


@dataclass
class Sample:
    planned: PlannedBid
    code: str
    latency: float
    # How late the bid left against its planned time: a saturated generator delays sends, and
    # latency alone would hide that (coordinated omission). lag + latency = intended response.
    lag: float = 0.0
    segments: dict[str, float] = field(default_factory=dict)


def plan_load(seed: int, rate: float, duration: float, auctions: list[UUID], *,
              burst: int = 5, bidders_per_auction: int = 20) -> list[PlannedBid]:
    """Round-robin over auctions; each auction's bids leave in bursts of ``burst`` that race
    for its compare-and-set, with amounts that tie, undercut and outbid."""
    _, _, increment_for = _bid_imports()
    rng = random.Random(seed)
    people = {a: [UUID(int=rng.getrandbits(128), version=4) for _ in range(bidders_per_auction)]
              for a in auctions}
    price = dict.fromkeys(auctions, STARTING_PRICE)
    total = max(len(auctions), int(rate * duration))
    plan = []
    for i in range(total):
        auction = auctions[(i // burst) % len(auctions)]
        step = rng.choice((-1, 0, 1, 1, 2))
        amount = max(STARTING_PRICE, price[auction] + increment_for(price[auction]) * step)
        price[auction] = max(price[auction], amount)
        plan.append(PlannedBid((i // burst) * burst / rate, auction,
                               rng.choice(people[auction]), amount))
    return plan


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))] * 1000


def percentiles(values: list[float]) -> dict[str, float]:
    return {"p50": round(pct(values, 0.50), 2), "p95": round(pct(values, 0.95), 2),
            "p99": round(pct(values, 0.99), 2)}


# ---------------------------------------------------------------------- segment timing


class Timed:
    """Proxy that adds the wall time of the listed async methods to a segment."""

    def __init__(self, target: Any, segments: dict[str, str]) -> None:
        self._target = target
        self._segments = segments

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._target, name)
        segment = self._segments.get(name)
        if segment is None or not callable(attribute):
            return attribute

        async def timed(*args: Any, **kwargs: Any) -> Any:
            began = time.perf_counter()
            try:
                return await attribute(*args, **kwargs)
            finally:
                timings = _timings.get()
                if timings is not None:
                    timings[segment] = timings.get(segment, 0.0) + time.perf_counter() - began

        return timed


def build_inproc(auctions: list[UUID]):
    """The bid service's real hot path, every adapter wrapped in a segment timer."""
    _bid_imports()
    from datetime import UTC, datetime, timedelta

    import fakeredis
    from prometheus_client import CollectorRegistry

    from app.adapters.auction_client import AuctionSnapshot
    from app.adapters.bid_repo import InMemoryBidRepository
    from app.adapters.kafka_producer import InMemoryBidEventPublisher
    from app.adapters.price_buffer import RedisPriceBuffer
    from app.adapters.pricing_client import StubPricingClient
    from app.domain.conflict import ConflictResolver
    from app.domain.idempotency import IdempotencyGuard
    from app.domain.sequencing import SequenceAllocator
    from app.service import BidMetrics, BidService

    closes = datetime.now(UTC) + timedelta(days=1)

    class OpenAuctions:
        async def get_state(self, auction_id):
            return AuctionSnapshot(auction_id=auction_id, seller_id=SELLER, state="OPEN",
                                   bid_permitted=True, currency="INR",
                                   starting_price=STARTING_PRICE, closes_at=closes,
                                   as_of=datetime.now(UTC))

    class AmpleFunds:
        async def available(self, bidder_id):
            return Decimal("10000000.00")

    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    publisher = InMemoryBidEventPublisher()
    raw_prices = RedisPriceBuffer(redis)
    prices = Timed(raw_prices, {"leader": "validation", "next_seq": "sequencing_cas",
                                "compare_and_set": "sequencing_cas",
                                "enqueue_for_flush": "enqueue_publish"})
    metrics = BidMetrics(CollectorRegistry())
    service = BidService(
        auctions=Timed(OpenAuctions(), {"get_state": "validation"}),
        pricing=Timed(StubPricingClient(), {"quote": "validation"}),
        funds=Timed(AmpleFunds(), {"available": "validation"}),
        prices=prices,
        publisher=Timed(publisher, {"publish": "enqueue_publish"}),
        idempotency=Timed(IdempotencyGuard(redis), {"claim": "idempotency",
                                                     "complete": "idempotency"}),
        bids=InMemoryBidRepository(), metrics=metrics, max_resolution_attempts=50,
    )
    # The resolver reads the leader again after a lost round: that is CAS work, not validation.
    cas_prices = Timed(raw_prices, {"leader": "sequencing_cas", "next_seq": "sequencing_cas",
                                    "compare_and_set": "sequencing_cas"})
    service.resolver = ConflictResolver(cas_prices, SequenceAllocator(cas_prices),
                                        max_attempts=50, clock=service.clock)
    return service, publisher, raw_prices, metrics


async def paced(plan: list[PlannedBid], fire) -> tuple[list[Sample], float]:
    loop = asyncio.get_running_loop()
    start = loop.time()

    async def one(planned: PlannedBid) -> Sample:
        delay = start + planned.at - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        lag = max(0.0, loop.time() - (start + planned.at))
        timings: dict[str, float] = {}
        _timings.set(timings)
        began = time.perf_counter()
        code = await fire(planned)
        return Sample(planned, code, time.perf_counter() - began, lag, timings)

    samples = await asyncio.gather(*(one(p) for p in plan))
    return list(samples), loop.time() - start


async def run_inproc(plan: list[PlannedBid], auctions: list[UUID], replays: int,
                     seed: int) -> dict[str, Any]:
    Leader, replay, tier_increment = _bid_imports()
    from zeo_common import ApiError
    from zeo_common.auth import Principal

    service, publisher, prices, metrics = build_inproc(auctions)

    async def fire(planned: PlannedBid) -> str:
        principal = Principal(user_id=planned.bidder, role="USER", kyc_status="NOT_SUBMITTED",
                              suspended=False)
        try:
            await service.place_bid(principal, planned.auction, planned.amount,
                                    f"rig-{uuid4()}", None)
        except ApiError as error:
            return error.code
        return "ACCEPTED"

    samples, elapsed = await paced(plan, fire)
    logs = defaultdict(list)
    for e in publisher.events:
        logs[UUID(e["auction_id"])].append(
            Leader(Decimal(e["amount"]), e["server_seq"], UUID(e["bid_id"]), UUID(e["bidder_id"])))
    disagree = [str(a) for a in auctions
                if not check_replays(logs[a], await prices.leader(a), replays, seed, replay,
                                     tier_increment)]
    summary = summarize(samples, elapsed, len(auctions))
    summary["cas_retries"] = int(metrics.cas_retries._value.get())
    summary["replay_agrees_all_auctions"] = not disagree
    summary["replay_disagreements"] = disagree
    return summary


def summarize(samples: list[Sample], elapsed: float, auctions: int) -> dict[str, Any]:
    latencies = [s.latency for s in samples]
    accepted = [s.latency for s in samples if s.code == "ACCEPTED"]
    segments = {}
    for name in SEGMENTS:
        segments[name] = percentiles([s.segments.get(name, 0.0) for s in samples])
    segments["other"] = percentiles(
        [max(0.0, s.latency - sum(s.segments.values())) for s in samples])
    return {
        "auctions": auctions,
        "bids": len(samples),
        "achieved_rate": round(len(samples) / elapsed, 1) if elapsed else 0.0,
        "outcomes": dict(Counter(s.code for s in samples)),
        "latency_ms": percentiles(latencies),
        "accepted_latency_ms": percentiles(accepted),
        "schedule_lag_ms": percentiles([s.lag for s in samples]),
        "intended_latency_ms": percentiles([s.lag + s.latency for s in samples]),
        "segments_ms": segments if any(s.segments for s in samples) else {},
        "within_budget_p95": pct([s.lag + s.latency for s in samples], 0.95)
        <= BUDGET_MS["total"],
    }


# ---------------------------------------------------------------------- HTTP mode


async def run_http(plan: list[PlannedBid], base_url: str, jwt_secret: str) -> dict[str, Any]:
    import httpx

    _bid_imports()
    from zeo_common.auth import JwtSettings, encode_access_token

    jwt = JwtSettings(secret=jwt_secret)
    tokens = {b: encode_access_token(jwt, user_id=b, role="USER", kyc_status="NOT_SUBMITTED",
                                     suspended=False) for b in {p.bidder for p in plan}}
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=1000)
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0, limits=limits) as http:

        async def fire(planned: PlannedBid) -> str:
            try:
                response = await http.post(
                    f"/api/v1/auctions/{planned.auction}/bids",
                    json={"amount": f"{planned.amount:.2f}"},
                    headers={"Authorization": f"Bearer {tokens[planned.bidder]}",
                             "Idempotency-Key": f"rig-{uuid4()}"})
            except httpx.HTTPError as exc:
                return type(exc).__name__
            if response.status_code == 202:
                return "ACCEPTED"
            return (response.json() if response.content else {}).get("code", "HTTP_ERROR")

        samples, elapsed = await paced(plan, fire)
    return summarize(samples, elapsed, len({p.auction for p in plan}))


# ---------------------------------------------------------------------- entry point


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Target bids/s | Achieved | Bids | p50 ms | p95 ms | p99 ms | "
             "p95 lag ms | p95 intended ms | CAS retries | Outcomes | Replay = live |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lat = r["latency_ms"]
        lines.append(
            f"| {r['target_rate']:g} | {r['achieved_rate']} | {r['bids']} | {lat['p50']} | "
            f"{lat['p95']} | {lat['p99']} | {r['schedule_lag_ms']['p95']} | "
            f"{r['intended_latency_ms']['p95']} | {r.get('cas_retries', '-')} | "
            f"{', '.join(f'{k} {v}' for k, v in sorted(r['outcomes'].items()))} | "
            f"{'yes' if r.get('replay_agrees_all_auctions', True) else 'NO'} |")
    if rows and rows[-1].get("segments_ms"):
        lines += ["", "| Segment (SDD 9.3) | Budget ms | " +
                  " | ".join(f"p95 @ {r['target_rate']:g}/s" for r in rows) + " |",
                  "|---|---|" + "---|" * len(rows)]
        for name in (*SEGMENTS, "other"):
            budget = BUDGET_MS.get(name, "-")
            lines.append(f"| {name} | {budget} | " +
                         " | ".join(str(r["segments_ms"][name]["p95"]) for r in rows) + " |")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=("inproc", "http"), default="inproc")
    parser.add_argument("--rate", type=float, default=1000.0, help="aggregate bids per second")
    parser.add_argument("--sweep", default="", help="comma-separated rates; overrides --rate")
    parser.add_argument("--auctions", type=int, default=50)
    parser.add_argument("--auction-ids", type=Path, help="HTTP mode: file of OPEN auction ids")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--burst", type=int, default=5)
    parser.add_argument("--replays", type=int, default=20)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--base-url", default="http://localhost:8004")
    parser.add_argument("--jwt-secret", default="zeo-dev-jwt-secret-not-for-production-use")
    parser.add_argument("--markdown", action="store_true", help="also print a Markdown table")
    args = parser.parse_args(argv)

    if args.auction_ids:
        auctions = [UUID(line.strip()) for line in args.auction_ids.read_text().splitlines()
                    if line.strip()]
    else:
        auctions = [UUID(int=0x5EED_0000 + i, version=4) for i in range(args.auctions)]
    rates = [float(r) for r in args.sweep.split(",") if r] or [args.rate]
    rows = []
    for rate in rates:
        plan = plan_load(args.seed, rate, args.duration, auctions, burst=args.burst)
        if args.mode == "inproc":
            result = await run_inproc(plan, auctions, args.replays, args.seed)
        else:
            result = await run_http(plan, args.base_url, args.jwt_secret)
        result = {"target_rate": rate, "mode": args.mode} | result
        rows.append(result)
        print(json.dumps(result))
    if args.markdown:
        print(markdown(rows))
    return 0 if all(r.get("replay_agrees_all_auctions", True) for r in rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
