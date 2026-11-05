"""Contract CT-1: Bid service -> Auction Orchestrator (Plan 7, #26; NFR-MAINT-3).

Proves that the bid accepted event produced by services/bid is strictly valid
against contracts/events/bid_accepted.v1.json and is consumed losslessly
by services/auction-orchestrator's bid.events consumer (parse_accepted, decode).
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
import yaml

from .conftest import CONTRACTS, REPO_ROOT

ORCHESTRATOR_DIR = REPO_ROOT / "services" / "auction-orchestrator"
_orch_str = str(ORCHESTRATOR_DIR)
_added_orch = False
if _orch_str not in sys.path:
    sys.path.insert(0, _orch_str)
    _added_orch = True

from app.adapters.bid_events import decode, parse_accepted  # type: ignore

# Clean up app from sys.modules so downstream suites can import their own service app
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
if _added_orch and _orch_str in sys.path:
    sys.path.remove(_orch_str)

import importlib.util
PRODUCER_PATH = REPO_ROOT / "services" / "bid" / "app" / "adapters" / "kafka_producer.py"
spec = importlib.util.spec_from_file_location("bid_kafka_producer", PRODUCER_PATH)
bid_producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bid_producer)
build_bid_accepted = bid_producer.build_bid_accepted

SCHEMA_PATH = CONTRACTS / "events" / "bid_accepted.v1.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def make_valid_event(**overrides):
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    kwargs = {
        "event_id": uuid4(),
        "bid_id": uuid4(),
        "auction_id": uuid4(),
        "bidder_id": uuid4(),
        "seller_id": uuid4(),
        "amount": Decimal("1500.00"),
        "currency": "INR",
        "server_seq": 1,
        "accepted_at": now,
        "auction_closes_at": now,
        "idempotency_key": "idemp-key-12345",
        "device_fingerprint": "fp_test_device_1",
        "increment_stale": False,
    }
    kwargs.update(overrides)
    return build_bid_accepted(**kwargs)


def test_ct1_producer_output_validates_against_json_schema():
    """Producer output conforms to the official Draft 2020-12 schema."""
    event = make_valid_event()
    errors = list(VALIDATOR.iter_errors(event))
    assert not errors, [e.message for e in errors]


def test_ct1_consumer_parses_producer_event_losslessly():
    """Auction orchestrator parses the producer's event into AcceptedBid."""
    bid_id = uuid4()
    auction_id = uuid4()
    bidder_id = uuid4()
    amount = Decimal("2750.00")
    seq = 42

    event = make_valid_event(
        bid_id=bid_id,
        auction_id=auction_id,
        bidder_id=bidder_id,
        amount=amount,
        server_seq=seq,
    )

    accepted = parse_accepted(event)
    assert accepted is not None
    assert accepted.bid_id == bid_id
    assert accepted.auction_id == auction_id
    assert accepted.bidder_id == bidder_id
    assert accepted.amount == amount
    assert accepted.server_seq == seq


def test_ct1_consumer_decode_bytes():
    """Full wire bytes -> JSON -> AcceptedBid decoding."""
    event = make_valid_event(amount=Decimal("1999.00"), server_seq=10)
    raw_bytes = json.dumps(event).encode("utf-8")

    decoded = decode(raw_bytes)
    assert decoded is not None
    assert decoded.amount == Decimal("1999.00")
    assert decoded.server_seq == 10


def test_ct1_consumer_rejects_schema_version_mismatch():
    """Consumer skips messages with unknown schema version (rule 4)."""
    event = make_valid_event()
    event["schema_version"] = 2
    assert parse_accepted(event) is None


@pytest.mark.parametrize("missing_field", ["auction_id", "bid_id", "server_seq", "amount", "bidder_id"])
def test_ct1_consumer_rejects_missing_required_fields(missing_field):
    """Consumer rejects events missing required fields without throwing."""
    event = make_valid_event()
    del event[missing_field]
    assert parse_accepted(event) is None


@pytest.mark.parametrize("bad_amount", ["1250", "1250.5", 1250.00, "-50.00", "invalid"])
def test_ct1_consumer_rejects_malformed_money(bad_amount):
    """Consumer rejects non-standard money formats."""
    event = make_valid_event()
    event["amount"] = bad_amount
    assert parse_accepted(event) is None


def test_ct1_consumer_handles_corrupt_bytes():
    """Malformed wire bytes return None, never raise exceptions."""
    assert decode(b"not json") is None
    assert decode(b"") is None
    assert decode(b"123") is None


def test_ct1_partition_key_and_topic_pin():
    """contracts/events/topics.yaml pins topic name and key to auction_id."""
    topics = yaml.safe_load((CONTRACTS / "events" / "topics.yaml").read_text(encoding="utf-8"))["topics"]
    bid_topic = next(t for t in topics if t["name"] == "bid.events")
    assert bid_topic["key"] == "auction_id"
    assert "bid_accepted.v1.json" in bid_topic["schemas"]
