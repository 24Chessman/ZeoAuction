"""The lifecycle timer (A2, A5, A6) and the bid.events consumer."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from app.adapters.auction_repo import StaleAuction, due_event
from app.adapters.bid_events import BidEventsConsumer, decode, parse_accepted
from app.timers import LifecycleTimer
from tests.support import NOW, draft


async def add(harness, **overrides):
    auction = replace(draft(), **overrides)
    await harness.repo.add(auction)
    return auction


def at(harness, moment):
    harness.service.clock = lambda: moment


async def test_tick_opens_closes_and_drains_when_due(harness):
    auction = await add(harness, state="SCHEDULED")
    at(harness, auction.opens_at - timedelta(seconds=1))
    assert await harness.service.tick() == []
    at(harness, auction.opens_at)
    assert await harness.service.tick() == [(auction.id, "open")]
    at(harness, auction.closes_at)
    assert await harness.service.tick() == [(auction.id, "close")]
    # A6 waits for the drain grace period after closing.
    at(harness, auction.closes_at + timedelta(seconds=1))
    assert await harness.service.tick() == []
    at(harness, auction.closes_at + timedelta(seconds=5))
    assert await harness.service.tick() == [(auction.id, "drained")]
    assert (await harness.repo.get(auction.id)).state == "CLOSED"
    assert harness.repo.lifecycle(auction.id) == ["create", "open", "close", "drained"]
    assert [e["to_state"] for e in harness.events.events] == ["OPEN", "CLOSING", "CLOSED"]


async def test_a_bid_landing_during_the_drain_becomes_the_winner(harness):
    auction = await add(harness, state="CLOSING", closing_since=NOW)
    late_bid = uuid4()
    from app.domain.anti_snipe import AcceptedBid

    await harness.service.on_bid_accepted(
        AcceptedBid(auction.id, late_bid, 4, auction.closes_at - timedelta(seconds=1))
    )
    at(harness, NOW + timedelta(seconds=5))
    await harness.service.tick()
    closed = await harness.repo.get(auction.id)
    assert closed.winning_bid_id == late_bid
    assert harness.events.events[-1]["winning_bid_id"] == str(late_bid)


async def test_a_lost_race_is_deferred_to_the_next_tick(harness, monkeypatch):
    auction = await add(harness, state="SCHEDULED")
    at(harness, auction.opens_at)

    async def stale(*args):
        raise StaleAuction(str(auction.id))

    monkeypatch.setattr(harness.repo, "save_transition", stale)
    assert await harness.service.tick() == []


def test_due_event():
    grace = timedelta(seconds=5)
    assert due_event(replace(draft(), state="DRAFT"), NOW + timedelta(days=9), grace) is None
    assert due_event(replace(draft(), state="CLOSING"), NOW, grace) == "drained"
    assert due_event(replace(draft(), state="CLOSED"), NOW + timedelta(days=9), grace) is None


async def test_timer_runs_until_stopped(harness):
    calls = []
    third = asyncio.Event()

    async def tick():
        calls.append(1)
        if len(calls) == 3:
            third.set()
        if len(calls) == 1:
            raise RuntimeError("database blip")  # logged, the loop goes on
        return []

    harness.service.tick = tick
    timer = LifecycleTimer(harness.service, interval_seconds=0.001)
    timer.start()
    await asyncio.wait_for(third.wait(), timeout=5)
    await timer.stop()
    await timer.stop()  # idempotent
    assert len(calls) >= 3


# ---------------------------------------------------------------- bid.events consumer


def accepted_event(**overrides):
    return {
        "event_id": str(uuid4()), "schema_version": 1, "auction_id": str(uuid4()),
        "bid_id": str(uuid4()), "bidder_id": str(uuid4()), "amount": "120.00",
        "server_seq": 3, "accepted_at": "2026-09-14T12:00:00Z", "idempotency_key": "key-12345",
    } | overrides


def test_parse_accepted_reads_the_contract_fields():
    bid = parse_accepted(accepted_event())
    assert bid.server_seq == 3
    assert bid.accepted_at.tzinfo is not None


def test_unknown_versions_and_garbage_are_skipped():
    assert parse_accepted(accepted_event(schema_version=2)) is None
    assert parse_accepted(accepted_event(server_seq="many")) is None
    assert decode(b"not json") is None
    assert decode(b"[1, 2]") is None


class FakeMessage:
    def __init__(self, value):
        self.value = value


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
        return self._iterate()

    async def _iterate(self):
        for value in self.values:
            yield FakeMessage(value)


async def test_consumer_applies_each_bid_then_commits():
    seen = []

    async def handler(bid):
        seen.append(bid.server_seq)

    values = [json.dumps(accepted_event(server_seq=n)).encode() for n in (1, 2)] + [b"junk"]
    consumer = FakeConsumer(values)
    await BidEventsConsumer(consumer, handler).run()
    assert seen == [1, 2]
    assert consumer.commits == 3
    assert consumer.started and consumer.stopped


async def test_consumer_retries_a_failing_bid_until_it_applies():
    attempts = []
    sleeps = []

    async def handler(bid):
        attempts.append(bid)
        if len(attempts) < 3:
            raise ConnectionError("database down")

    async def sleep(seconds):
        sleeps.append(seconds)

    consumer = BidEventsConsumer(FakeConsumer([]), handler, sleep=sleep)
    await consumer.handle(json.dumps(accepted_event()).encode())
    assert len(attempts) == 3
    assert sleeps == [1.0, 1.0]
