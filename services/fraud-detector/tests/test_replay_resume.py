"""#52 gate: the scaffold consumes the replayed dataset in order and survives a restart.

The labelled dataset is published with the real replay tool (``dataset/replay.py``) into a
12-partition fake of ``bid.events``. A consumer in group ``fraud-detector`` reads part of it and
stops; a second process in the same group resumes from the committed offsets. Together they see
every event exactly once, each auction strictly in ``server_seq`` order. A crash between
handling and committing redelivers that one event (at-least-once) and nothing is lost.
"""

import json
from collections import defaultdict

import pytest

from app.consumer import FraudConsumer
from dataset.generator import DatasetConfig, generate, write
from dataset.replay import publish, read_events
from tests.kafka_fakes import CommitFailed, FakeBroker

SMALL = DatasetConfig(n_auctions=30, n_rings=8, n_honest_accounts=100, n_clean_sellers=8,
                      min_clean_auctions=8)
TOPIC, GROUP = "bid.events", "fraud-detector"


@pytest.fixture
async def broker(tmp_path):
    write(generate(SMALL), tmp_path)
    events = list(read_events(tmp_path / "dataset-v1.jsonl.gz"))
    fake = FakeBroker(partitions=12)
    await publish(events, fake)
    fake.expected = events
    return fake


class Recorder:
    """The scoring hook: records the order features arrive in, per auction."""

    def __init__(self):
        self.seen = defaultdict(list)

    async def __call__(self, features):
        self.seen[features.auction_id].append(features.server_seq)


def assert_in_order(seen: dict[str, list[int]]):
    for auction, seqs in seen.items():
        assert seqs == sorted(seqs), f"auction {auction} out of order"
        assert len(seqs) == len(set(seqs)), f"auction {auction} saw a duplicate"


def by_auction(events) -> dict[str, list[int]]:
    expected = defaultdict(list)
    for e in events:
        expected[e["auction_id"]].append(e["server_seq"])
    return {a: sorted(s) for a, s in expected.items()}


async def test_one_pass_consumes_every_event_in_order(broker):
    recorder = Recorder()
    consumer = FraudConsumer(broker.consumer(TOPIC, GROUP), on_features=recorder)
    await consumer.run()
    assert consumer.stats.accepted == len(broker.expected)
    assert consumer.stats.duplicate == consumer.stats.skipped == 0
    assert_in_order(recorder.seen)
    assert dict(recorder.seen) == by_auction(broker.expected)


async def test_a_restart_resumes_from_the_committed_offsets(broker):
    first, second = Recorder(), Recorder()
    half = len(broker.expected) // 2
    await FraudConsumer(broker.consumer(TOPIC, GROUP, limit=half), on_features=first).run()
    resumed = FraudConsumer(broker.consumer(TOPIC, GROUP), on_features=second)
    await resumed.run()
    assert sum(map(len, first.seen.values())) == half
    assert resumed.stats.accepted == len(broker.expected) - half
    merged = defaultdict(list)
    for seen in (first.seen, second.seen):
        for auction, seqs in seen.items():
            merged[auction].extend(seqs)
    assert_in_order(merged)
    assert dict(merged) == by_auction(broker.expected)


async def test_a_crash_before_commit_redelivers_only_that_event(broker):
    first, second = Recorder(), Recorder()
    with pytest.raises(CommitFailed):
        await FraudConsumer(broker.consumer(TOPIC, GROUP, fail_commit_at=50),
                            on_features=first).run()
    await FraudConsumer(broker.consumer(TOPIC, GROUP), on_features=second).run()
    total = sum(map(len, first.seen.values())) + sum(map(len, second.seen.values()))
    assert total == len(broker.expected) + 1  # the uncommitted event, handled twice
    for seen in (first.seen, second.seen):
        assert_in_order(seen)


async def test_another_group_reads_the_topic_independently(broker):
    await FraudConsumer(broker.consumer(TOPIC, GROUP)).run()
    other = FraudConsumer(broker.consumer(TOPIC, "fraud-detector-replay-check"))
    await other.run()
    assert other.stats.accepted == len(broker.expected)


async def test_events_are_published_keyed_by_auction(broker):
    partitions_of = defaultdict(set)
    for partition, entries in enumerate(broker.logs[TOPIC]):
        for value in entries:
            partitions_of[json.loads(value)["auction_id"]].add(partition)
    assert all(len(p) == 1 for p in partitions_of.values())
