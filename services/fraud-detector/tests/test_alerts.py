import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from app.adapters.alert_producer import InMemoryAlertProducer, KafkaAlertProducer, encode
from app.adapters.alert_repo import (
    EvaluationRun,
    InMemoryAlertRepository,
    PostgresAlertRepository,
)
from app.alerts import (
    AlertMetrics,
    AlertOutcome,
    AlertPublisher,
    LateAlertError,
    alert_id_for,
    build_shill_alert,
    must_precede_close,
)
from app.features import BidderFeatures
from app.pipeline import ScoringPipeline
from app.scorer import ShillDetector, ShillScorer

START = datetime(2026, 10, 5, 12, tzinfo=UTC)
CLOSES = START + timedelta(hours=1)
SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "events"
                     / "shill_alert.v1.json").read_text(encoding="utf-8"))
AUCTION = "6e7c59ab-62ad-42d6-9097-b0491f3b017e"
BIDDER = "6132caef-8328-475c-acd4-a15a9d71c090"


def suspect(**overrides) -> BidderFeatures:
    base = BidderFeatures(
        auction_id=AUCTION, bidder_id=BIDDER, seller_id="s1", server_seq=4, bids_in_auction=3,
        share_of_auction=0.5, seller_link_ratio=1.0, fingerprint_sharers=1,
        bids_per_minute=2.0, interarrival_cv=0.1, fingerprint_overlap=1,
        interarrival_stdev=3.0, observed_at=START, auction_closes_at=CLOSES)
    return replace(base, **overrides)


def decision(**overrides):
    return ShillDetector().observe(suspect(**overrides))


class Clock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


def publisher(clock=None):
    producer, repo = InMemoryAlertProducer(), InMemoryAlertRepository()
    metrics = AlertMetrics(CollectorRegistry())
    return AlertPublisher(producer, repo, metrics=metrics, clock=clock or Clock()), producer, repo


def count(pub, outcome):
    return pub.metrics.alerts.labels(outcome=outcome)._value.get()


def test_must_precede_close():
    must_precede_close(START, CLOSES)
    with pytest.raises(LateAlertError):
        must_precede_close(CLOSES, CLOSES)  # at the close is already too late
    with pytest.raises(LateAlertError):
        must_precede_close(CLOSES + timedelta(seconds=1), CLOSES)


def test_the_alert_matches_the_shill_alert_v1_contract():
    alert = build_shill_alert(decision(), START)
    assert set(alert) <= set(SCHEMA["properties"])
    assert set(SCHEMA["required"]) <= set(alert)
    assert alert["schema_version"] == 1
    assert set(alert["signals"]) <= set(SCHEMA["properties"]["signals"]["properties"])
    assert alert["suspect_bidder_ids"] == [BIDDER]
    assert alert["raised_at"] == "2026-10-05T12:00:00Z"
    assert alert["auction_closes_at"] == "2026-10-05T13:00:00Z"
    assert 0 <= alert["score"] <= 1
    assert alert["ring_id"] is None


def test_the_alert_id_is_stable_for_the_same_auction_and_bidder():
    assert alert_id_for(AUCTION, BIDDER) == alert_id_for(AUCTION, BIDDER)
    assert alert_id_for(AUCTION, BIDDER) != alert_id_for(AUCTION, "other")
    with pytest.raises(ValueError):
        build_shill_alert(decision(auction_closes_at=None), START)


async def test_an_alert_before_close_is_stored_and_published():
    pub, producer, repo = publisher()
    assert await pub.publish(decision()) is AlertOutcome.PUBLISHED
    assert len(producer.alerts) == 1
    assert list(repo.alerts) == [producer.alerts[0]["alert_id"]]
    assert count(pub, "published") == 1


async def test_a_late_alert_is_recorded_as_a_miss_and_never_published():
    pub, producer, repo = publisher(Clock(CLOSES + timedelta(minutes=5)))
    assert await pub.publish(decision()) is AlertOutcome.LATE
    assert producer.alerts == []
    assert len(repo.misses()) == 1
    assert count(pub, "late") == 1


async def test_an_alert_without_a_close_time_is_dropped():
    pub, producer, repo = publisher()
    assert await pub.publish(decision(auction_closes_at=None)) is AlertOutcome.NO_CLOSE
    assert producer.alerts == [] and repo.alerts == {}


async def test_a_replay_raises_the_alert_at_the_bids_own_time():
    pub, producer, _ = publisher(Clock(CLOSES + timedelta(days=30)))  # the wall clock is late
    pipeline = ScoringPipeline(ShillDetector(ShillScorer()), pub, replay_time=True)
    assert await pipeline(suspect()) is AlertOutcome.PUBLISHED
    assert producer.alerts[0]["raised_at"] == "2026-10-05T12:00:00Z"
    assert await pipeline(suspect()) is None  # already a suspect
    pipeline.forget_auction(AUCTION)
    assert pipeline.detector.suspects(AUCTION) == {}


async def test_re_scoring_after_a_restart_stores_nothing_twice():
    _, _, repo = publisher()
    for _ in range(2):
        pub = AlertPublisher(InMemoryAlertProducer(), repo, clock=Clock())
        await pub.publish(decision())
    assert len(repo.alerts) == 1


def test_the_kafka_message_is_keyed_by_auction():
    alert = build_shill_alert(decision(), START)
    key, value = encode(alert)
    assert key == AUCTION.encode()
    assert json.loads(value) == alert


class FakeKafka:
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
        return {0, 1, 2} if topic == "fraud.alerts" else set()


async def test_the_kafka_producer_sends_to_fraud_alerts():
    kafka = FakeKafka()
    producer = KafkaAlertProducer(kafka)
    await producer.start()
    await producer.publish(build_shill_alert(decision(), START))
    await producer.stop()
    assert kafka.started and kafka.stopped
    assert kafka.sent[0][0] == "fraud.alerts" and kafka.sent[0][1] == AUCTION.encode()
    assert await producer.ready()


class FakePool:
    def __init__(self, status="INSERT 0 1"):
        self.log = []
        self.status = status

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def execute(self, sql, *args):
        self.log.append((sql, args))
        return self.status

    async def fetchval(self, sql, *args):
        self.log.append((sql, args))
        return 7


async def test_postgres_insert_is_idempotent_on_alert_id():
    pool = FakePool()
    alert = build_shill_alert(decision(), START)
    assert await PostgresAlertRepository(pool).save_alert(alert) is True
    sql, args = pool.log[0]
    assert sql.startswith("INSERT INTO fraud.fraud_alerts")
    assert "ON CONFLICT (alert_id) DO NOTHING" in sql
    assert args[0] == alert["alert_id"] and args[3] == Decimal("1.0000")
    assert json.loads(args[4]) == alert["signals"]
    assert args[5] == START and args[6] == CLOSES
    assert await PostgresAlertRepository(FakePool("INSERT 0 0")).save_alert(alert) is False


async def test_evaluation_runs_are_recorded():
    pool = FakePool()
    run = EvaluationRun("v1", "shill-v1", Decimal("0.6000"), Decimal("0.9025"),
                        Decimal("0.9325"), 0)
    assert await PostgresAlertRepository(pool).record_evaluation(run) == 7
    assert pool.log[0][0].startswith("INSERT INTO fraud.evaluation_runs")
    assert pool.log[0][1] == ("v1", "shill-v1", Decimal("0.6000"), Decimal("0.9025"),
                              Decimal("0.9325"), 0)
    memory = InMemoryAlertRepository()
    assert await memory.record_evaluation(run) == 1
