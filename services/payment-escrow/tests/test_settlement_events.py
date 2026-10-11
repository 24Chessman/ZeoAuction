"""SettlementStep v1 on payment.events, the Kafka publisher, settings and the worker."""

import asyncio
import json
from uuid import uuid4

import pytest
import yaml

from app.adapters.kafka_producer import (
    STEP_TYPES,
    KafkaSettlementEventPublisher,
    build_settlement_step,
    encode,
)
from app.main import build_app, build_port
from app.payment_port.mock_adapter import MockPaymentAdapter
from app.payment_port.razorpay_adapter import RazorpayAdapter
from app.settings import Settings
from app.worker import SettlementWorker
from tests.support import NOW, SETTINGS, order
from zeo_common.contract_testing import assert_matches_contract, find_contracts_dir
from zeo_common.settings import SettingsError


@pytest.mark.parametrize("step", STEP_TYPES)
def test_every_step_matches_the_contract(step):
    event = build_settlement_step(event_id=uuid4(), order=order(), step=step, occurred_at=NOW)
    assert_matches_contract(event, "events/settlement_step.v1.json")
    assert event["occurred_at"] == "2026-10-10T12:00:00Z"


def test_unknown_steps_are_refused():
    with pytest.raises(ValueError):
        build_settlement_step(event_id=uuid4(), order=order(), step="AUTHORIZED", occurred_at=NOW)


def test_events_are_keyed_by_order():
    event = build_settlement_step(event_id=uuid4(), order=order(), step="HELD", occurred_at=NOW)
    key, value = encode(event)
    assert key == event["order_id"].encode() and json.loads(value) == event


def test_the_topic_is_declared_with_payment_as_producer():
    topics = yaml.safe_load((find_contracts_dir() / "events" / "topics.yaml").read_text(
        encoding="utf-8"))["topics"]
    topic = next(t for t in topics if t["name"] == "payment.events")
    assert topic["key"] == "order_id" and "payment-escrow" in topic["producers"]


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


async def test_kafka_publisher_sends_keyed_events():
    producer = FakeProducer()
    publisher = KafkaSettlementEventPublisher(producer)
    await publisher.start()
    event = build_settlement_step(event_id=uuid4(), order=order(), step="HELD", occurred_at=NOW)
    await publisher.publish(event)
    assert producer.sent[0][:2] == ("payment.events", event["order_id"].encode())
    assert await publisher.ready()
    await publisher.stop()
    assert producer.started and producer.stopped


def test_settings_default_to_the_mock_adapter(monkeypatch):
    for name in ("PAYMENT_ADAPTER", "RAZORPAY_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.payment_adapter == "mock" and settings.payment_window_hours == 48
    assert isinstance(build_port(settings), MockPaymentAdapter)
    monkeypatch.setenv("PAYMENT_ADAPTER", "stripe")
    with pytest.raises(SettingsError):
        Settings.from_env()


def test_razorpay_is_built_from_test_keys_only(monkeypatch):
    monkeypatch.setenv("PAYMENT_ADAPTER", "razorpay")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "hook")
    monkeypatch.setenv("RAZORPAY_LINKED_ACCOUNT", "acc_demo")
    port = build_port(Settings.from_env())
    assert isinstance(port, RazorpayAdapter) and port._linked_account_for(uuid4()) == "acc_demo"
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_abc")
    with pytest.raises(ValueError, match="test mode only"):
        build_port(Settings.from_env())


async def test_the_worker_runs_passes_until_stopped():
    app = build_app(SETTINGS)
    service = app.state.payment_service
    passes = []
    third = asyncio.Event()

    async def run_due_work():
        passes.append(1)
        if len(passes) == 1:
            raise RuntimeError("one bad pass does not stop the worker")
        if len(passes) == 3:
            third.set()
        return []

    service.run_due_work = run_due_work
    worker = SettlementWorker(service, interval_seconds=0.001)
    worker.start()
    await asyncio.wait_for(third.wait(), timeout=5)
    await worker.stop()
    await worker.stop()  # idempotent
    assert len(passes) >= 3
