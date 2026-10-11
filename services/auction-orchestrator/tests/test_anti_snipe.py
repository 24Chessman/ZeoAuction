"""A4 anti-snipe (#32): bids in the guard interval extend the auction, up to the cap."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from app.domain.anti_snipe import AcceptedBid, apply_bid, should_extend
from app.domain.auction import DEFAULT_POLICY
from tests.support import NOW, draft

POLICY = Path(__file__).resolve().parents[3] / "config" / "settlement-policy.yaml"


def open_auction(**overrides):
    closes = NOW + timedelta(minutes=10)
    values = {"state": "OPEN", "closes_at": closes, "original_closes_at": closes} | overrides
    return replace(draft(), **values)


def bid(auction, seq, before_close: timedelta):
    return AcceptedBid(auction_id=auction.id, bid_id=uuid4(), server_seq=seq,
                       accepted_at=auction.closes_at - before_close)


def test_policy_values_match_the_settlement_policy_file():
    anti_snipe = yaml.safe_load(POLICY.read_text(encoding="utf-8"))["anti_snipe"]
    assert anti_snipe == {
        "guard_interval_seconds": DEFAULT_POLICY.guard_interval_seconds,
        "extension_seconds": DEFAULT_POLICY.extension_seconds,
        "max_extensions": DEFAULT_POLICY.max_extensions,
    }


def test_a_bid_before_the_guard_interval_only_records_the_leader():
    auction = open_auction()
    accepted = bid(auction, 1, timedelta(minutes=5))
    outcome = apply_bid(auction, accepted, NOW)
    assert not outcome.extended
    assert outcome.auction.state == "OPEN"
    assert (outcome.auction.last_bid_seq, outcome.auction.leading_bid_id) == (1, accepted.bid_id)
    assert outcome.auction.closes_at == auction.closes_at


def test_a_bid_inside_the_guard_interval_extends():
    auction = open_auction()
    accepted = bid(auction, 1, timedelta(seconds=30))
    outcome = apply_bid(auction, accepted, NOW)
    assert outcome.extended
    assert outcome.auction.state == "EXTENDED"
    assert outcome.auction.closes_at == auction.closes_at + timedelta(seconds=120)
    assert outcome.auction.leading_bid_id == accepted.bid_id


def test_the_guard_boundary_is_exclusive():
    auction = open_auction()
    assert not should_extend(auction, auction.closes_at - timedelta(seconds=120))
    assert should_extend(auction, auction.closes_at - timedelta(seconds=119))


def test_a_bidding_war_extends_exactly_max_extensions_times():
    auction = open_auction()
    extensions = 0
    for seq in range(1, 30):
        outcome = apply_bid(auction, bid(auction, seq, timedelta(seconds=10)), NOW)
        extensions += outcome.extended
        auction = outcome.auction
    assert extensions == auction.max_extensions == 10
    assert auction.extension_count == 10
    assert auction.closes_at == open_auction().closes_at + timedelta(seconds=120 * 10)
    assert auction.last_bid_seq == 29  # bids past the cap still stand


def test_a_redelivered_bid_never_extends_twice():
    auction = open_auction()
    accepted = bid(auction, 3, timedelta(seconds=10))
    once = apply_bid(auction, accepted, NOW).auction
    again = apply_bid(once, accepted, NOW)
    assert again.duplicate and not again.extended
    assert again.auction == once
    assert apply_bid(once, replace(accepted, server_seq=2), NOW).duplicate


def test_closing_auctions_record_the_bid_without_extending():
    auction = open_auction(state="CLOSING")
    outcome = apply_bid(auction, bid(auction, 1, timedelta(seconds=5)), NOW)
    assert not outcome.extended
    assert outcome.auction.state == "CLOSING"
    assert outcome.auction.last_bid_seq == 1


# ---------------------------------------------------------------- through the service


async def opened(harness):
    auction = open_auction()
    await harness.repo.add(auction)
    return auction


async def test_service_extends_and_publishes_auction_extended(harness):
    auction = await opened(harness)
    accepted = bid(auction, 1, timedelta(seconds=20))
    assert await harness.service.on_bid_accepted(accepted) is True
    stored = await harness.repo.get(auction.id)
    assert (stored.state, stored.extension_count) == ("EXTENDED", 1)
    (event,) = harness.events.events
    assert (event["event"], event["to_state"], event["extension_count"]) == (
        "extend", "EXTENDED", 1)
    assert event["actor_id"] is None
    assert harness.repo.lifecycle(auction.id) == ["create", "extend"]


async def test_service_records_a_plain_bid_without_a_transition(harness):
    auction = await opened(harness)
    assert await harness.service.on_bid_accepted(bid(auction, 1, timedelta(minutes=5))) is False
    assert (await harness.repo.get(auction.id)).last_bid_seq == 1
    assert harness.repo.lifecycle(auction.id) == ["create"]
    assert harness.events.events == []


async def test_service_ignores_duplicates_unknown_auctions_and_closed_ones(harness):
    auction = await opened(harness)
    accepted = bid(auction, 1, timedelta(seconds=20))
    await harness.service.on_bid_accepted(accepted)
    assert await harness.service.on_bid_accepted(accepted) is False
    assert await harness.service.on_bid_accepted(replace(accepted, auction_id=uuid4())) is False
    closed = replace(open_auction(), state="CLOSED")
    await harness.repo.add(closed)
    assert await harness.service.on_bid_accepted(bid(closed, 1, timedelta(seconds=5))) is False
    assert (await harness.repo.get(closed.id)).last_bid_seq == 0


async def test_service_retries_after_losing_a_race(harness, monkeypatch):
    auction = await opened(harness)
    original = harness.repo.record_bid
    calls = []

    async def racing(before, after):
        calls.append(before.version)
        if len(calls) == 1:
            # A timer transition lands between our read and our write.
            current = harness.repo.auctions[before.id]
            harness.repo.auctions[before.id] = replace(current, version=current.version + 1)
        await original(before, after)

    monkeypatch.setattr(harness.repo, "record_bid", racing)
    await harness.service.on_bid_accepted(bid(auction, 1, timedelta(minutes=5)))
    assert calls == [1, 2]
    assert (await harness.repo.get(auction.id)).last_bid_seq == 1


async def test_service_gives_up_after_repeated_races(harness, monkeypatch):
    from app.adapters.auction_repo import StaleAuction

    auction = await opened(harness)

    async def always_stale(before, after):
        raise StaleAuction(str(before.id))

    monkeypatch.setattr(harness.repo, "record_bid", always_stale)
    with pytest.raises(StaleAuction):
        await harness.service.on_bid_accepted(bid(auction, 1, timedelta(minutes=5)))
