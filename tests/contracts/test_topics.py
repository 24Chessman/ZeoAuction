"""contracts/events/topics.yaml and infra/kafka/create-topics.sh must describe the same topics."""

import re

import yaml

from .conftest import CONTRACTS, REPO_ROOT

TOPICS_FILE = CONTRACTS / "events" / "topics.yaml"
TOPICS = yaml.safe_load(TOPICS_FILE.read_text(encoding="utf-8"))["topics"]
SCRIPT = (REPO_ROOT / "infra" / "kafka" / "create-topics.sh").read_text(encoding="utf-8")

CREATE_LINE = re.compile(r"^create\s+(\S+)\s+(\d+)(.*)$", re.MULTILINE)


def script_topics() -> dict[str, dict]:
    found = {}
    for name, partitions, rest in CREATE_LINE.findall(SCRIPT):
        retention = re.search(r"retention\.ms=\$\(\((\d+) \* DAY_MS\)\)", rest)
        policy = re.search(r"cleanup\.policy=(\S+)", rest)
        found[name] = {
            "partitions": int(partitions),
            "retention_days": int(retention.group(1)) if retention else None,
            "cleanup_policy": policy.group(1) if policy else "delete",
        }
    return found


def test_script_creates_exactly_the_declared_topics():
    assert set(script_topics()) == {t["name"] for t in TOPICS}


def test_partitions_retention_and_policy_match():
    created = script_topics()
    for topic in TOPICS:
        actual = created[topic["name"]]
        assert actual["partitions"] == topic["partitions"], topic["name"]
        assert actual["retention_days"] == topic["retention_days"], topic["name"]
        assert actual["cleanup_policy"] == topic["cleanup_policy"], topic["name"]


def test_every_declared_schema_exists():
    for topic in TOPICS:
        for schema in topic["schemas"]:
            assert (CONTRACTS / "events" / schema).exists(), f"{topic['name']}: {schema}"


def test_bid_events_is_keyed_by_auction():
    bid_events = next(t for t in TOPICS if t["name"] == "bid.events")
    assert bid_events["key"] == "auction_id"
