import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import yaml

from app.adapters.kafka_producer import (
    BID_EVENTS_TOPIC,
    InMemoryBidEventPublisher,
    KafkaBidEventPublisher,
    build_bid_accepted,
    encode,
)
from tests.fakes import AUCTION_ID, SELLER_ID, FakeAioKafkaProducer
from zeo_common.contract_testing import assert_matches_contract, find_contracts_dir


def event(**overrides):
    fields = {
        "event_id": uuid4(),
        "bid_id": uuid4(),
        "auction_id": AUCTION_ID,
        "bidder_id": uuid4(),
        "seller_id": SELLER_ID,
        "amount": Decimal("1250.00"),
        "currency": "USD",
        "server_seq": 42,
        "accepted_at": datetime(2026, 8, 20, 10, 15, 30, 120000, tzinfo=UTC),
        "auction_closes_at": datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        "idempotency_key": "c0ffee00-bid-0001",
        "device_fingerprint": "fp_9a8b7c6d",
        "increment_stale": False,
    } | overrides
    return build_bid_accepted(**fields)


def test_event_conforms_to_bid_accepted_v1():
    assert_matches_contract(event(), "events/bid_accepted.v1.json")


def test_event_without_close_time_or_fingerprint_conforms():
    assert_matches_contract(
        event(auction_closes_at=None, device_fingerprint=None), "events/bid_accepted.v1.json"
    )
    assert "auction_closes_at" not in event(auction_closes_at=None)


def test_money_is_a_two_decimal_string_and_timestamps_end_in_z():
    body = event(amount=Decimal("5"))
    assert body["amount"] == "5.00"
    assert body["accepted_at"] == "2026-08-20T10:15:30.120000Z"


def test_key_is_the_auction_id():
    key, value = encode(event())
    assert key == str(AUCTION_ID).encode()
    assert json.loads(value)["auction_id"] == str(AUCTION_ID)


def test_topic_matches_the_frozen_topology():
    topics = yaml.safe_load((find_contracts_dir() / "events" / "topics.yaml").read_text())
    bid_events = next(t for t in topics["topics"] if t["name"] == BID_EVENTS_TOPIC)
    assert bid_events["key"] == "auction_id"
    assert "bid" in bid_events["producers"]
    assert "bid_accepted.v1.json" in bid_events["schemas"]


async def test_publish_waits_for_the_broker_acknowledgement():
    producer = FakeAioKafkaProducer()
    publisher = KafkaBidEventPublisher(producer)
    await publisher.start()
    body = event()
    await publisher.publish(body)
    ((topic, key, value),) = producer.sent
    assert topic == "bid.events"
    assert key == str(AUCTION_ID).encode()
    assert json.loads(value) == body
    assert await publisher.ready()
    await publisher.stop()
    assert producer.started is False


async def test_broker_failure_propagates_so_the_client_is_not_acknowledged():
    producer = FakeAioKafkaProducer()
    producer.fail_next = True
    with pytest.raises(ConnectionError):
        await KafkaBidEventPublisher(producer).publish(event())
    assert producer.sent == []


async def test_connect_builds_an_aiokafka_producer_without_contacting_the_broker():
    from aiokafka import AIOKafkaProducer

    publisher = KafkaBidEventPublisher.connect("localhost:29092")
    assert isinstance(publisher.producer, AIOKafkaProducer)
    assert publisher.topic == "bid.events"


async def test_in_memory_publisher():
    publisher = InMemoryBidEventPublisher()
    publisher.fail_next = True
    with pytest.raises(ConnectionError):
        await publisher.publish(event())
    await publisher.publish(event())
    assert len(publisher.events) == 1
