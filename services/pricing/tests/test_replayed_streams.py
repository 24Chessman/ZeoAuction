"""Pricing behaviour on replayed bid streams (#45, Plan 5).

Two streams:

* **the labelled bid log** (``tests/fixtures/fraud/dataset-v1.jsonl.gz``, 10 817 bids over 28 days,
  bidding wars and shill bursts included): ordinary traffic. The dynamic increment must stay on
  the base ladder, never refuse a bid the base ladder accepted, and never flag an auction hot;
* **a contended auction**: Poisson arrivals around the 30 bpm hot threshold for 20 minutes.
  The 30/15 hysteresis must hold the flag steady where one threshold would flap, and the
  increment must stay within [base, base x multiplier].

Measured 2026-10-19: on the log every one of 10 317 quotes is the base increment, and none is
hot. Around 28-32 bpm the 30/15 policy changes the flag once in 20 minutes, where 30/30 changes
it 47-59 times. The defaults (``HOT_ENTER_BPM=30``, ``HOT_EXIT_BPM=15``,
``PRICING_SATURATION_BPM=60``) are kept.
"""

import gzip
import json
import random
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from app.adapters.bid_consumer import ObservedBid
from app.domain.hot_auction import HotAuctions, HotPolicy
from app.domain.increment import DEFAULT_LADDER, band_for
from tests.support import AUCTION, T0, Clock, make_service

BID_LOG = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fraud" / \
    "dataset-v1.jsonl.gz"


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_ordinary_traffic_stays_on_the_base_ladder():
    clock = Clock()
    service = make_service(clock)
    current: dict[str, Decimal] = {}
    quotes = above_base = refused = hot = 0
    with gzip.open(BID_LOG, "rt", encoding="utf-8") as lines:
        for line in lines:
            event = json.loads(line)
            auction, amount = event["auction_id"], Decimal(event["amount"])
            clock.now = max(clock.now, _time(event["accepted_at"]))
            if auction in current:
                quote = await service.quote(UUID(auction), current[auction])
                base = band_for(DEFAULT_LADDER, current[auction]).base_increment
                assert quote.min_increment >= base  # the floor the bid replay relies on
                quotes += 1
                above_base += quote.min_increment > base
                refused += amount < quote.min_next_bid
                hot += quote.hot
            await service.on_bid_accepted(ObservedBid(auction, int(event["server_seq"]),
                                                      _time(event["accepted_at"]), amount))
            current[auction] = amount
    assert quotes > 10_000
    assert (above_base, refused, hot) == (0, 0, 0)


async def contended(policy: HotPolicy, mean_bpm: float, minutes: int = 20, seed: int = 1):
    rng = random.Random(seed)
    clock = Clock()
    service = make_service(clock)
    service.hot = HotAuctions(policy)
    at, seq, price, changes, was_hot = T0, 0, Decimal("1000.00"), 0, False
    ratios = []
    while at < T0 + timedelta(minutes=minutes):
        at += timedelta(seconds=rng.expovariate(mean_bpm / 60))
        seq += 1
        clock.now = at
        quote = await service.quote(AUCTION, price)
        rule = band_for(DEFAULT_LADDER, price)
        ratios.append(quote.min_increment / rule.base_increment)
        assert rule.base_increment <= quote.min_increment <= (
            rule.base_increment * rule.velocity_multiplier)
        price = quote.min_next_bid
        await service.on_bid_accepted(ObservedBid(str(AUCTION), seq, at, price))
        if service.hot.is_hot(str(AUCTION)) != was_hot:
            changes, was_hot = changes + 1, not was_hot
    return changes, max(ratios)


@pytest.mark.parametrize("mean_bpm", [28, 30, 32])
async def test_hysteresis_holds_the_hot_flag_steady_near_the_threshold(mean_bpm):
    steady, peak = await contended(HotPolicy(enter_bpm=30, exit_bpm=15), mean_bpm)
    flapping, _ = await contended(HotPolicy(enter_bpm=30, exit_bpm=30), mean_bpm)
    assert steady <= 2
    assert flapping > 10 * max(steady, 1)
    assert peak > 1  # a contended auction does get a larger increment


async def test_a_calm_auction_is_never_flagged():
    changes, peak = await contended(HotPolicy(enter_bpm=30, exit_bpm=15), mean_bpm=3)
    assert changes == 0 and peak <= Decimal("1.25")  # a chance cluster nudges it, no more
