import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.consumer import FraudConsumer, decode
from app.main import build_app
from app.settings import Settings
from app.windows import AuctionWindows, Outcome
from tests.kafka_fakes import FakeBroker

START = datetime(2026, 10, 1, 12, tzinfo=UTC)


def event(seq, *, auction="a1", bidder="b1", closes_in=60, **extra) -> dict:
    at = START + timedelta(seconds=seq)
    return {"event_id": f"e-{auction}-{seq}", "schema_version": 1, "auction_id": auction,
            "bidder_id": bidder, "seller_id": "s1", "amount": "10.00", "server_seq": seq,
            "accepted_at": at.isoformat().replace("+00:00", "Z"),
            "auction_closes_at": (START + timedelta(minutes=closes_in)).isoformat(),
            "idempotency_key": f"k-{seq:08d}"} | extra


def raw(e: dict) -> bytes:
    return json.dumps(e).encode()


# ------------------------------------------------------------------ windows


def test_window_keeps_order_drops_redeliveries_and_counts_gaps():
    windows = AuctionWindows(max_events=3)
    assert windows.add(event(1))[0] is Outcome.ACCEPTED
    assert windows.add(event(1))[0] is Outcome.DUPLICATE
    windows.add(event(2))
    windows.add(event(5))  # 3 and 4 lost their compare-and-set: a normal gap
    outcome, window = windows.add(event(6))
    assert outcome is Outcome.ACCEPTED
    assert window.sequence() == [2, 5, 6]  # bounded to max_events
    assert (window.seen, window.gaps, window.last_seq) == (4, 1, 6)
    assert windows.add(event(4))[0] is Outcome.DUPLICATE


def test_window_close_follows_anti_snipe_extensions_and_expires():
    windows = AuctionWindows(close_grace=timedelta(minutes=10))
    windows.add(event(1, closes_in=60))
    windows.add(event(2, closes_in=62))
    windows.add(event(3, closes_in=61))
    windows.add(event(1, auction="a2", auction_closes_at=None))
    assert windows.get("a1").closes_at == START + timedelta(minutes=62)
    assert windows.expire(START + timedelta(minutes=71)) == []
    assert windows.expire(START + timedelta(minutes=73)) == ["a1"]
    assert len(windows) == 1 and windows.get("a1") is None


def test_windows_need_room_for_one_event():
    with pytest.raises(ValueError):
        AuctionWindows(max_events=0)


# ------------------------------------------------------------------ consumer


@pytest.mark.parametrize("value", [
    b"junk", b"[]", b"\xff", raw(event(1, schema_version=2)), raw(event(1, server_seq="x")),
    json.dumps({"schema_version": 1, "auction_id": "a1"}).encode(),
])
def test_decode_rejects_what_it_cannot_score(value):
    assert decode(value) is None


async def test_handle_feeds_features_to_the_scoring_hook():
    scored = []

    async def hook(features):
        scored.append((features.bidder_id, features.bids_in_auction))

    consumer = FraudConsumer(None, on_features=hook)
    assert await consumer.handle(raw(event(1))) is Outcome.ACCEPTED
    assert await consumer.handle(raw(event(2))) is Outcome.ACCEPTED
    assert await consumer.handle(raw(event(2))) is Outcome.DUPLICATE
    assert await consumer.handle(b"junk") is None
    assert scored == [("b1", 1), ("b1", 2)]
    assert (consumer.stats.accepted, consumer.stats.duplicate, consumer.stats.skipped) == (2, 1, 1)


async def test_a_failing_hook_never_stops_consumption():
    async def hook(features):
        raise RuntimeError("scorer bug")

    consumer = FraudConsumer(None, on_features=hook)
    assert await consumer.handle(raw(event(1))) is Outcome.ACCEPTED
    assert consumer.stats.accepted == 1


async def test_closed_auctions_are_expired_periodically():
    consumer = FraudConsumer(None, clock=lambda: START + timedelta(hours=3), expire_every=2)
    await consumer.handle(raw(event(1, auction="old", closes_in=1)))
    await consumer.handle(raw(event(1, auction="new", closes_in=600)))
    assert consumer.windows.get("old") is None
    assert consumer.windows.get("new") is not None
    assert consumer.metrics.windows._value.get() == 1


async def test_run_commits_each_message_and_records_positions():
    broker = FakeBroker(partitions=2)
    for seq in (1, 2, 3):
        await broker.send_and_wait("bid.events", raw(event(seq)), b"a1")
    kafka = broker.consumer("bid.events", "fraud-detector")
    consumer = FraudConsumer(kafka)
    await consumer.run()
    assert kafka.started and kafka.stopped and kafka.commits == 3
    (partition, position), = consumer.stats.positions.items()
    assert position == 3 and partition[0] == "bid.events"


def test_the_worker_serves_health_without_a_broker():
    client = TestClient(build_app(Settings(kafka_bootstrap_servers="", consume_bids=False)))
    with client:
        assert client.get("/healthz").json()["service"] == "fraud-detector"
        assert "fraud_open_windows" in client.get("/metrics").text
