"""#94: reconnect snapshot by server_seq, and price coalescing under backpressure."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import fakeredis
import pytest

from app.backpressure import Outbox, OutboxClosed, OutboxOverflow
from app.connections import CLOSE_TRY_AGAIN_LATER, Connection, GatewayMetrics, Hub, Limits
from app.fanout import FanOut
from app.rooms import RedisSnapshots, RoomState, Snapshots, StaleSnapshot
from tests.support import ALICE, AUCTION, BOB, JWT, bid_event, client, url
from zeo_common.auth import Principal


def price(seq: int, auction: str = AUCTION) -> dict:
    return {"type": "price_update", "auction_id": auction, "current_price": f"{100 + seq}.00",
            "min_next_bid": f"{105 + seq}.00", "server_seq": seq}


# ---------------------------------------------------------------- reconnect over the socket


def test_resubscribing_behind_gets_the_snapshot():
    with client() as test:
        test.portal.call(test.app.state.fanout.on_bid_accepted, bid_event(7, BOB, "150.00"))
        with test.websocket_connect(url(ALICE)) as ws:
            ws.send_json({"type": "subscribe", "auction_id": AUCTION, "last_seq": 4})
            snapshot = ws.receive_json()
            assert (snapshot["type"], snapshot["server_seq"], snapshot["current_price"]) == (
                "price_update", 7, "150.00")


def test_a_client_already_up_to_date_gets_no_snapshot():
    with client() as test:
        test.portal.call(test.app.state.fanout.on_bid_accepted, bid_event(7, BOB))
        with test.websocket_connect(url(ALICE)) as ws:
            ws.send_json({"type": "subscribe", "auction_id": AUCTION, "last_seq": 7})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


def test_a_first_subscribe_without_last_seq_gets_the_current_price():
    with client() as test:
        test.portal.call(test.app.state.fanout.on_bid_accepted, bid_event(2, BOB))
        with test.websocket_connect(url(ALICE)) as ws:
            ws.send_json({"type": "subscribe", "auction_id": AUCTION})
            assert ws.receive_json()["server_seq"] == 2


async def test_a_restarted_gateway_answers_from_the_shared_snapshot():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    before = Snapshots(RedisSnapshots(redis))
    state = RoomState(AUCTION, "150.00", "155.00", 7, str(BOB), str(uuid4()))
    await before.advance(state)
    after_restart = Snapshots(RedisSnapshots(redis))
    assert await after_restart.get(AUCTION) == state
    assert 0 < await redis.ttl(f"ws:room:{AUCTION}") <= 3600


async def test_shared_snapshot_never_moves_backwards():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    shared = RedisSnapshots(redis)
    newer = RoomState(AUCTION, "150.00", "155.00", 7, str(BOB), str(uuid4()))
    assert await shared.advance(newer)
    assert not await shared.advance(RoomState(AUCTION, "140.00", "145.00", 6, str(ALICE), "x"))
    assert await shared.get(AUCTION) == newer


async def test_every_instance_fans_out_even_if_another_wrote_redis_first():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    first, second = Snapshots(RedisSnapshots(redis)), Snapshots(RedisSnapshots(redis))
    state = RoomState(AUCTION, "150.00", "155.00", 7, str(BOB), str(uuid4()))
    await first.advance(state)
    second.local[AUCTION] = RoomState(AUCTION, "140.00", "145.00", 6, str(ALICE), "a")
    previous = await second.advance(state)  # instance two still fans out seq 7
    assert previous.server_seq == 6
    with pytest.raises(StaleSnapshot):
        await second.advance(state)


async def test_a_redis_outage_does_not_stop_fan_out():
    class Down:
        async def get(self, auction_id):
            raise ConnectionError("redis down")

        async def advance(self, state):
            raise ConnectionError("redis down")

    snapshots = Snapshots(Down())
    state = RoomState(AUCTION, "150.00", "155.00", 7, str(BOB), "b")
    assert await snapshots.advance(state) is None
    assert await snapshots.get(AUCTION) == state


# ---------------------------------------------------------------- the outbox


async def test_waiting_prices_are_coalesced_last_write_wins():
    outbox = Outbox(limit=10)
    assert outbox.put(price(1)) is False
    assert outbox.put(price(2)) is True
    assert outbox.put(price(1, auction="other")) is False
    assert outbox.put(price(3)) is True
    assert len(outbox) == 2
    assert outbox.coalesced == 2
    assert [m["server_seq"] for m in (await outbox.get(), await outbox.get())] == [1, 3]


async def test_notifications_are_never_coalesced_and_keep_their_order():
    outbox = Outbox(limit=10)
    outbox.put(price(1))
    outbox.put({"type": "outbid", "auction_id": AUCTION, "your_bid_id": "a"})
    outbox.put({"type": "outbid", "auction_id": AUCTION, "your_bid_id": "b"})
    outbox.put(price(2))  # the newer price goes after the alerts that preceded it
    delivered = [await outbox.get() for _ in range(3)]
    assert [m["type"] for m in delivered] == ["outbid", "outbid", "price_update"]
    assert delivered[2]["server_seq"] == 2


async def test_a_full_outbox_overflows_on_notifications_only():
    outbox = Outbox(limit=2)
    outbox.put({"type": "notification", "kind": "x"})
    outbox.put({"type": "notification", "kind": "y"})
    with pytest.raises(OutboxOverflow):
        outbox.put({"type": "notification", "kind": "z"})
    outbox.put(price(1))  # prices never overflow: at most one per room


async def test_a_closed_outbox_drains_then_stops():
    outbox = Outbox()
    outbox.put(price(1))
    outbox.close()
    assert outbox.put(price(2)) is False
    assert (await outbox.get())["server_seq"] == 1
    with pytest.raises(OutboxClosed):
        await outbox.get()


async def test_get_waits_for_the_next_message():
    outbox = Outbox()
    waiting = asyncio.create_task(outbox.get())
    await asyncio.sleep(0)
    assert not waiting.done()
    outbox.put(price(9))
    assert (await waiting)["server_seq"] == 9


# ---------------------------------------------------------------- slow watchers


class StuckSocket:
    """A watcher whose network never drains: send_json blocks forever."""

    def __init__(self):
        self.sent = []
        self.closed_with = None
        self.blocked = asyncio.Event()

    async def send_json(self, message):
        self.sent.append(message)
        await self.blocked.wait()

    async def close(self, code):
        self.closed_with = code


class FastSocket(StuckSocket):
    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code):
        self.closed_with = code


def make_hub(**limits) -> Hub:
    from prometheus_client import CollectorRegistry

    return Hub(JWT, GatewayMetrics(CollectorRegistry()), Snapshots(), Limits(**limits))


def attach(hub: Hub, socket, user=None) -> Connection:
    principal = Principal(user_id=user or uuid4(), role="USER", kyc_status="NOT_SUBMITTED",
                          suspended=False)
    connection = Connection(socket, principal, datetime.now(UTC) + timedelta(minutes=15),
                            hub.limits, hub.metrics)
    hub.rooms.connect(connection)
    hub.rooms.join(connection, AUCTION)
    return connection


async def test_a_stuck_watcher_neither_blocks_fan_out_nor_other_watchers():
    hub = make_hub()
    stuck, fast = StuckSocket(), FastSocket()
    slow_conn, fast_conn = attach(hub, stuck), attach(hub, fast)
    writers = [asyncio.create_task(c.write_loop()) for c in (slow_conn, fast_conn)]
    fanout = FanOut(hub)
    for seq in range(1, 51):
        await asyncio.wait_for(fanout.on_bid_accepted(bid_event(seq, BOB, f"{100 + seq}.00")),
                               timeout=1)
        await asyncio.sleep(0)  # one scheduling turn: enough for a healthy writer
    assert len(fast.sent) == 50  # the fast watcher saw every price
    assert len(stuck.sent) == 1  # the stuck one is still sending its first...
    assert len(slow_conn.outbox) == 1  # ...and holds only the newest price, coalesced
    for writer in writers:
        writer.cancel()


async def test_a_watcher_drowning_in_alerts_is_disconnected_to_resync():
    hub = make_hub(outbox_limit=3)
    stuck = StuckSocket()
    connection = attach(hub, stuck, user=ALICE)
    writer = asyncio.create_task(connection.write_loop())
    for _ in range(6):
        connection.send({"type": "notification", "kind": "x"})
    assert connection.close_code == CLOSE_TRY_AGAIN_LATER
    stuck.blocked.set()
    await asyncio.wait_for(writer, timeout=1)
    assert stuck.closed_with == CLOSE_TRY_AGAIN_LATER


async def test_fan_out_to_500_watchers_stays_well_under_100_ms():
    hub = make_hub()
    sockets = [FastSocket() for _ in range(500)]
    connections = [attach(hub, s) for s in sockets]
    writers = [asyncio.create_task(c.write_loop()) for c in connections]
    fanout = FanOut(hub)
    durations = []
    for seq in range(1, 41):
        started = time.perf_counter()
        await fanout.on_bid_accepted(bid_event(seq, BOB, f"{100 + seq}.00"))
        await asyncio.sleep(0)  # let the writers run
        durations.append(time.perf_counter() - started)
    durations.sort()
    p95 = durations[int(0.95 * len(durations)) - 1]
    assert p95 < 0.1, f"p95 fan-out {p95 * 1000:.1f} ms"
    assert all(len(s.sent) >= 1 for s in sockets)
    for writer in writers:
        writer.cancel()
