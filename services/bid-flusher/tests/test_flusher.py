import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import fakeredis
import pytest
from prometheus_client import CollectorRegistry

from app.flusher import (
    DEAD_LETTER_KEY,
    FLUSH_PENDING_KEY,
    BatchFlusher,
    BatchPolicy,
    FlusherMetrics,
)
from app.main import build_app
from app.replay import replay_bid_events
from app.settings import Settings
from app.store import InMemoryBidStore, row_from_event
from zeo_common.contract_testing import assert_matches_contract

AUCTION = UUID("00000000-0000-4000-8000-000000000201")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
T0 = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0.timestamp()

    def __call__(self) -> float:
        return self.now


def event(seq: int, auction: UUID = AUCTION, amount: int | None = None) -> dict:
    body = {
        "event_id": str(uuid4()),
        "schema_version": 1,
        "auction_id": str(auction),
        "bid_id": str(uuid4()),
        "bidder_id": str(uuid4()),
        "seller_id": str(SELLER),
        "amount": f"{amount if amount is not None else 100 + seq * 5}.00",
        "currency": "USD",
        "server_seq": seq,
        "accepted_at": (T0 + timedelta(seconds=seq)).isoformat().replace("+00:00", "Z"),
        "idempotency_key": f"key-{uuid4()}",
        "device_fingerprint": None,
        "increment_stale": False,
    }
    assert_matches_contract(body, "events/bid_accepted.v1.json")
    return body


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def store():
    return InMemoryBidStore()


@pytest.fixture
def clock():
    return Clock()


def flusher(redis, store, clock, max_size=3, max_age=0.5):
    return BatchFlusher(redis, store, BatchPolicy(max_size, max_age),
                        FlusherMetrics(CollectorRegistry()), clock=clock)


async def enqueue(redis, clock, *events):
    """The record format written by services/bid/app/adapters/price_buffer.py."""
    for e in events:
        await redis.rpush(FLUSH_PENDING_KEY, json.dumps(
            {"event": e, "enqueued_at_ms": int(clock() * 1000)}))


async def test_flushes_when_the_batch_reaches_its_size(redis, store, clock):
    f = flusher(redis, store, clock, max_size=3, max_age=60)
    await enqueue(redis, clock, event(1), event(2))
    assert await f.flush_once() == 0
    assert store.rows == {}
    await enqueue(redis, clock, event(3))
    assert await f.flush_once() == 3
    assert await redis.llen(FLUSH_PENDING_KEY) == 0
    assert sorted(r.server_seq for r in store.rows.values()) == [1, 2, 3]


async def test_flushes_when_the_oldest_bid_reaches_its_age(redis, store, clock):
    f = flusher(redis, store, clock, max_size=100, max_age=0.5)
    await enqueue(redis, clock, event(1))
    clock.now += 0.4
    assert await f.flush_once() == 0
    clock.now += 0.1
    assert await f.flush_once() == 1


async def test_a_batch_never_exceeds_its_size(redis, store, clock):
    f = flusher(redis, store, clock, max_size=3)
    await enqueue(redis, clock, *(event(s) for s in range(1, 8)))
    await f.drain()
    assert store.batches == [3, 3, 1]
    assert len(store.rows) == 7


async def test_database_failure_keeps_the_batch_queued(redis, store, clock):
    f = flusher(redis, store, clock)
    await enqueue(redis, clock, *(event(s) for s in range(1, 4)))
    store.fail_next = True
    with pytest.raises(ConnectionError):
        await f.flush_once()
    assert await redis.llen(FLUSH_PENDING_KEY) == 3
    assert await f.flush_once() == 3


async def test_rewriting_a_batch_after_a_crash_creates_no_duplicates(redis, store, clock):
    events = [event(s) for s in range(1, 4)]
    await enqueue(redis, clock, *events)
    await store.insert_batch([row_from_event(e) for e in events])  # wrote, crashed before trim
    assert await flusher(redis, store, clock).flush_once() == 3
    assert len(store.rows) == 3


async def test_unparseable_records_are_dead_lettered_not_blocking(redis, store, clock):
    await redis.rpush(FLUSH_PENDING_KEY, "{not json")
    await enqueue(redis, clock, event(1))
    await redis.rpush(FLUSH_PENDING_KEY, json.dumps({"event": {"bid_id": "x"}}))
    assert await flusher(redis, store, clock).flush_once(force=True) == 1
    assert await redis.llen(DEAD_LETTER_KEY) == 2
    assert await redis.llen(FLUSH_PENDING_KEY) == 0


async def test_run_loop_flushes_and_drains_on_stop(redis, store, clock):
    f = flusher(redis, store, clock, max_size=2, max_age=60)
    stop = asyncio.Event()
    task = asyncio.create_task(f.run(stop, poll_seconds=0.01))
    await enqueue(redis, clock, event(1), event(2), event(3))
    for _ in range(100):
        if len(store.rows) >= 2:
            break
        await asyncio.sleep(0.01)
    assert len(store.rows) == 2  # the third is below size and age
    stop.set()
    await task
    assert len(store.rows) == 3  # graceful shutdown drained it


async def test_run_loop_survives_a_database_outage(redis, store, clock):
    f = flusher(redis, store, clock, max_size=1)
    store.fail_next = True
    await enqueue(redis, clock, event(1))
    stop = asyncio.Event()
    task = asyncio.create_task(f.run(stop, poll_seconds=0.01))
    for _ in range(300):
        if store.rows:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await task
    assert len(store.rows) == 1


# ---------------------------------------------------------------------- Kafka replay recovery


class LogSource:
    def __init__(self, events):
        self.log = list(events)

    async def events(self):
        for e in self.log:
            yield e


async def test_crash_recovery_by_replay_restores_the_unflushed_batch(redis, store, clock):
    """The DoD demonstration: Redis loses flush:pending; Kafka still has every bid."""
    published = [event(s) for s in range(1, 11)]  # on bid.events before each 202
    await enqueue(redis, clock, *published)
    f = flusher(redis, store, clock, max_size=4, max_age=60)
    assert await f.flush_once() == 4             # one batch made it to PostgreSQL
    await redis.flushall()                        # crash: the queue and hot keys are gone
    assert await f.flush_once() == 0

    report = await replay_bid_events(LogSource(published), store, redis)

    assert report.rows_restored == 6
    assert sorted(r.server_seq for r in store.rows.values()) == list(range(1, 11))
    assert await redis.get(f"seq:{AUCTION}") == "10"
    leader = await redis.hgetall(f"price:{AUCTION}")
    assert (leader["server_seq"], leader["amount"]) == ("10", "150.00")


async def test_replay_is_idempotent(redis, store):
    log = [event(s) for s in range(1, 6)]
    await replay_bid_events(LogSource(log), store, redis)
    again = await replay_bid_events(LogSource(log), store, redis)
    assert again.rows_restored == 0
    assert len(store.rows) == 5


async def test_replay_never_lowers_live_redis_state(redis, store):
    await redis.set(f"seq:{AUCTION}", 50)
    await redis.hset(f"price:{AUCTION}", mapping={"amount": "900.00", "server_seq": 50,
                                                  "bid_id": str(uuid4()), "bidder_id": "b"})
    await replay_bid_events(LogSource([event(1), event(2)]), store, redis)
    assert await redis.get(f"seq:{AUCTION}") == "50"
    assert (await redis.hgetall(f"price:{AUCTION}"))["amount"] == "900.00"


async def test_replay_handles_many_auctions_in_interleaved_order(store):
    other = uuid4()
    log = [event(1), event(1, other), event(2, other), event(2), event(3)]
    report = await replay_bid_events(LogSource(log), store, batch_size=2)
    assert report.rows_restored == 5
    assert report.auctions == {AUCTION, other}
    assert await store.max_seq_by_auction() == {AUCTION: 3, other: 2}


async def test_replay_ignores_unknown_schema_versions(store):
    future = event(1) | {"schema_version": 2}
    report = await replay_bid_events(LogSource([future, event(2)]), store)
    assert (report.skipped_unknown_version, report.rows_restored) == (1, 1)


def test_settings_defaults(monkeypatch):
    for name in ("FLUSH_BATCH_MAX_SIZE", "FLUSH_BATCH_MAX_AGE_MS", "REPLAY_ON_START"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert (settings.batch_max_size, settings.batch_max_age_ms, settings.replay_on_start) == (
        500, 500, True)


def test_metrics_are_exposed():
    from fastapi.testclient import TestClient

    with TestClient(build_app(start_worker=False)) as client:
        body = client.get("/metrics").text
    assert "bid_flush_rows_total" in body
    assert "bid_flush_pending" in body
