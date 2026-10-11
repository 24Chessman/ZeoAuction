import json
from datetime import UTC, datetime
from pathlib import Path

from dataset.generator import DatasetConfig, generate, write
from dataset.replay import in_publish_order, publish, read_events, shift_to

SMALL = DatasetConfig(n_auctions=30, n_rings=8, n_honest_accounts=100, n_clean_sellers=8,
                      min_clean_auctions=8)


class RecordingProducer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, value, key):
        self.sent.append((topic, key, json.loads(value)))


def written(tmp_path: Path) -> list[dict]:
    write(generate(SMALL), tmp_path)
    return list(read_events(tmp_path / "dataset-v1.jsonl.gz"))


async def test_replay_publishes_every_event_keyed_by_auction(tmp_path):
    events = written(tmp_path)
    producer = RecordingProducer()
    assert await publish(events, producer) == len(events)
    assert {topic for topic, _, _ in producer.sent} == {"bid.events"}
    assert all(key == value["auction_id"].encode() for _, key, value in producer.sent)


async def test_each_auction_is_published_in_server_seq_order(tmp_path):
    producer = RecordingProducer()
    await publish(list(reversed(written(tmp_path))), producer)
    last_seq = {}
    for _, _, event in producer.sent:
        assert event["server_seq"] == last_seq.get(event["auction_id"], 0) + 1
        last_seq[event["auction_id"]] = event["server_seq"]


async def test_rate_limit_spaces_the_sends(tmp_path, monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("dataset.replay.asyncio.sleep", fake_sleep)
    events = written(tmp_path)[:5]
    await publish(events, RecordingProducer(), rate_per_second=50)
    assert sleeps == [0.02] * 5


def test_shift_moves_every_timestamp_by_one_offset(tmp_path):
    events = written(tmp_path)
    target = datetime(2030, 1, 1, tzinfo=UTC)
    shifted = shift_to(events, target)
    assert max(e["auction_closes_at"] for e in shifted) == "2030-01-01T00:00:00.000Z"
    assert [e["server_seq"] for e in in_publish_order(shifted)] == [
        e["server_seq"] for e in in_publish_order(events)]
    assert shift_to([], target) == []
