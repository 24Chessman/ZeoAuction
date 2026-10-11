"""#93: Kafka-driven room fan-out, outbid alerts to the displaced bidder only."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import fakeredis

from app.fanout import AUCTION_EVENTS, BID_EVENTS, FanoutConsumer, Increments, tier_increment
from tests.support import ALICE, AUCTION, BOB, bid_event, client, state_event, url

OTHER_AUCTION = str(uuid4())


def subscribe(ws, auction=AUCTION, last_seq=0):
    ws.send_json({"type": "subscribe", "auction_id": auction, "last_seq": last_seq})
    ws.send_json({"type": "ping"})  # the pong proves the subscribe was processed
    assert ws.receive_json() == {"type": "pong"}


def fan(test, event):
    return test.portal.call(test.app.state.fanout.on_bid_accepted, event)


def test_two_watchers_both_receive_the_price_update():
    with client() as test, test.websocket_connect(url(ALICE)) as alice, \
            test.websocket_connect(url(BOB)) as bob:
        subscribe(alice)
        subscribe(bob)
        assert fan(test, bid_event(1, uuid4(), "120.00")) == 2
        expected = {"type": "price_update", "auction_id": AUCTION, "current_price": "120.00",
                    "min_next_bid": "125.00", "server_seq": 1}
        assert alice.receive_json() == expected
        assert bob.receive_json() == expected


def test_only_the_displaced_bidder_is_outbid():
    with client() as test, test.websocket_connect(url(ALICE)) as alice, \
            test.websocket_connect(url(BOB)) as bob:
        subscribe(alice)
        subscribe(bob)
        alice_bid = str(uuid4())
        fan(test, bid_event(1, ALICE, "120.00", bid_id=alice_bid))
        alice.receive_json()
        bob.receive_json()
        fan(test, bid_event(2, BOB, "125.00"))
        assert alice.receive_json()["server_seq"] == 2
        outbid = alice.receive_json()
        assert outbid == {"type": "outbid", "auction_id": AUCTION, "your_bid_id": alice_bid,
                          "current_price": "125.00", "server_seq": 2}
        assert bob.receive_json()["type"] == "price_update"
        bob.send_json({"type": "ping"})
        assert bob.receive_json() == {"type": "pong"}  # no outbid for the new leader


def test_the_outbid_alert_reaches_the_bidder_outside_the_room():
    with client() as test, test.websocket_connect(url(ALICE)) as alice:
        subscribe(alice, OTHER_AUCTION)  # watching something else
        fan(test, bid_event(1, ALICE, "120.00"))
        fan(test, bid_event(2, BOB, "125.00"))
        assert alice.receive_json()["type"] == "outbid"


def test_raising_your_own_lead_is_not_an_outbid():
    with client() as test, test.websocket_connect(url(ALICE)) as alice:
        subscribe(alice)
        fan(test, bid_event(1, ALICE, "120.00"))
        fan(test, bid_event(2, ALICE, "130.00"))
        assert [alice.receive_json()["type"] for _ in range(2)] == ["price_update"] * 2
        alice.send_json({"type": "ping"})
        assert alice.receive_json() == {"type": "pong"}


def test_stale_and_unknown_version_events_are_skipped():
    with client() as test, test.websocket_connect(url(ALICE)) as alice:
        subscribe(alice)
        assert fan(test, bid_event(5, BOB)) == 1
        assert fan(test, bid_event(5, BOB)) == 0  # redelivered
        assert fan(test, bid_event(4, BOB)) == 0  # older
        assert fan(test, bid_event(6, BOB) | {"schema_version": 2}) == 0


def test_unsubscribed_watchers_stop_receiving():
    with client() as test, test.websocket_connect(url(ALICE)) as alice:
        subscribe(alice)
        alice.send_json({"type": "unsubscribe", "auction_id": AUCTION})
        alice.send_json({"type": "ping"})
        assert alice.receive_json() == {"type": "pong"}
        assert fan(test, bid_event(1, BOB)) == 0


def test_extension_and_close_are_pushed_to_the_room():
    with client() as test, test.websocket_connect(url(ALICE)) as alice:
        subscribe(alice)
        on_state = test.app.state.fanout.on_auction_event
        extended = state_event("extend", "OPEN", "EXTENDED")
        winner = str(uuid4())
        assert test.portal.call(on_state, extended) == 1
        assert test.portal.call(on_state, state_event("close", "OPEN", "CLOSING")) == 0
        assert test.portal.call(on_state, state_event("close", "CLOSING", "CLOSED",
                                                      winning_bid_id=winner)) == 1
        assert test.portal.call(on_state, extended | {"schema_version": 9}) == 0
        assert alice.receive_json() == {"type": "auction_extended", "auction_id": AUCTION,
                                        "new_closes_at": extended["closes_at"]}
        assert alice.receive_json() == {"type": "auction_closed", "auction_id": AUCTION,
                                        "winning_bid_id": winner}


def test_fanout_latency_is_measured():
    with client() as test, test.websocket_connect(url(ALICE)) as alice:
        subscribe(alice)
        fan(test, bid_event(1, BOB, accepted_at=datetime.now(UTC) - timedelta(milliseconds=30)))
        alice.receive_json()
        metrics = test.get("/metrics").text
        assert "ws_fanout_latency_seconds_count 1.0" in metrics
        assert 'ws_messages_sent_total{type="price_update"} 1.0' in metrics


def test_dispatch_routes_by_topic_and_survives_garbage():
    with client() as test, test.websocket_connect(url(ALICE)) as alice:
        subscribe(alice)
        dispatch = test.app.state.fanout.dispatch
        test.portal.call(dispatch, BID_EVENTS, b"not json")
        test.portal.call(dispatch, BID_EVENTS, b"[1]")
        test.portal.call(dispatch, BID_EVENTS, json.dumps({"schema_version": 1}).encode())
        test.portal.call(dispatch, "other.topic", json.dumps(bid_event(1, BOB)).encode())
        test.portal.call(dispatch, BID_EVENTS, json.dumps(bid_event(1, BOB)).encode())
        test.portal.call(dispatch, AUCTION_EVENTS,
                         json.dumps(state_event("extend", "OPEN", "EXTENDED")).encode())
        assert alice.receive_json()["type"] == "price_update"
        assert alice.receive_json()["type"] == "auction_extended"


async def test_increments_prefer_the_cached_pricing_value():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    increments = Increments(redis)
    assert await increments.for_price(AUCTION, Decimal("120.00")) == tier_increment(
        Decimal("120.00")) == Decimal("5.00")
    await redis.set(f"inc:{AUCTION}", "7.00")
    assert await increments.for_price(AUCTION, Decimal("120.00")) == Decimal("7.00")
    await redis.set(f"inc:{AUCTION}", "garbage")
    assert await increments.for_price(AUCTION, Decimal("6000.00")) == Decimal("50.00")


class FakeMessage:
    def __init__(self, topic, value):
        self.topic, self.value = topic, value


class FakeConsumer:
    def __init__(self, messages):
        self.messages = messages
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for message in self.messages:
            yield message


async def test_consumer_dispatches_and_survives_a_failing_message():
    seen = []

    async def dispatch(topic, value):
        seen.append(topic)
        if len(seen) == 1:
            raise RuntimeError("boom")

    consumer = FakeConsumer([FakeMessage(BID_EVENTS, b"{}"), FakeMessage(AUCTION_EVENTS, b"{}")])
    await FanoutConsumer(consumer, dispatch).run()
    assert seen == [BID_EVENTS, AUCTION_EVENTS]
    assert consumer.started and consumer.stopped
