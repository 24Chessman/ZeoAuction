"""``AuctionStateChanged v1`` on ``auction.events`` for every transition (#32)."""

import json
from dataclasses import replace
from uuid import uuid4

from app.adapters.kafka_producer import (
    AUCTION_EVENTS_TOPIC,
    KafkaAuctionEventPublisher,
    build_state_changed,
    encode,
)
from app.domain.lifecycle import SYSTEM, transition
from tests.support import NOW, draft
from zeo_common.contract_testing import assert_matches_contract

SCHEMA = "events/auction_state_changed.v1.json"


class FakeProducer:
    def __init__(self):
        self.sent = []
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def send_and_wait(self, topic, value, key):
        self.sent.append((topic, key, value))

    async def partitions_for(self, topic):
        return {0, 1}


def test_every_lifecycle_event_produces_a_contract_valid_message(harness):
    auction_id = harness.created()
    harness.drive(auction_id, "publish", "open", "close", "drained")
    events = harness.events.events
    assert [(e["event"], e["from_state"], e["to_state"]) for e in events] == [
        ("publish", "DRAFT", "SCHEDULED"),
        ("open", "SCHEDULED", "OPEN"),
        ("close", "OPEN", "CLOSING"),
        ("close", "CLOSING", "CLOSED"),  # A6 drained, under the v1 contract's name
    ]
    for event in events:
        assert_matches_contract(event, SCHEMA)
        assert event["auction_id"] == auction_id
    assert len({e["event_id"] for e in events}) == 4


def test_extension_and_winner_are_carried():
    before = replace(draft(), state="OPEN")
    after = transition(before, "extend", now=NOW, actor=SYSTEM)
    event = build_state_changed(event_id=uuid4(), before=before, after=after, event="extend",
                                actor_id=None, occurred_at=NOW)
    assert event["closes_at"].endswith("Z")
    assert event["extension_count"] == 1
    assert_matches_contract(event, SCHEMA)
    winner = uuid4()
    closed = replace(after, state="CLOSED", winning_bid_id=winner)
    drained = build_state_changed(event_id=uuid4(), before=replace(after, state="CLOSING"),
                                  after=closed, event="drained", actor_id=None, occurred_at=NOW)
    assert drained["winning_bid_id"] == str(winner)
    assert_matches_contract(drained, SCHEMA)


def test_cancel_by_the_seller_is_published(harness):
    auction_id = harness.created()
    harness.drive(auction_id, "cancel")
    (event,) = harness.events.events
    assert (event["event"], event["to_state"]) == ("cancel", "CANCELLED")
    assert_matches_contract(event, SCHEMA)


def test_a_broker_outage_does_not_undo_the_transition(harness):
    auction_id = harness.created()
    harness.events.fail_next = True
    published = harness.drive(auction_id, "publish")
    assert published["state"] == "SCHEDULED"
    assert harness.events.events == []
    metrics = harness.client.get("/metrics").text
    assert "auction_events_publish_failures_total 1.0" in metrics


def test_messages_are_keyed_by_auction_id():
    before = draft()
    event = build_state_changed(event_id=uuid4(), before=before,
                                after=replace(before, state="SCHEDULED"), event="publish",
                                actor_id=before.seller_id, occurred_at=NOW)
    key, value = encode(event)
    assert key == str(before.id).encode()
    assert json.loads(value) == event


async def test_kafka_publisher_sends_to_auction_events():
    producer = FakeProducer()
    publisher = KafkaAuctionEventPublisher(producer)
    await publisher.start()
    before = draft()
    event = build_state_changed(event_id=uuid4(), before=before,
                                after=replace(before, state="SCHEDULED"), event="publish",
                                actor_id=None, occurred_at=NOW)
    await publisher.publish(event)
    assert await publisher.ready()
    await publisher.stop()
    ((topic, key, _),) = producer.sent
    assert (topic, key) == (AUCTION_EVENTS_TOPIC, str(before.id).encode())
    assert producer.started and producer.stopped
