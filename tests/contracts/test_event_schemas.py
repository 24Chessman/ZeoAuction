"""Event schemas are valid JSON Schema, their examples conform, and money is never a float."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from .conftest import CONTRACTS

EVENTS = CONTRACTS / "events"
SCHEMAS = sorted(EVENTS.glob("*.v1.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validator_for(schema_path: Path) -> Draft202012Validator:
    schema = load(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_every_schema_has_an_example():
    assert SCHEMAS, "no event schemas found"
    for schema_path in SCHEMAS:
        example = EVENTS / "examples" / schema_path.name
        assert example.exists(), f"missing example for {schema_path.name}"


@pytest.mark.parametrize("schema_path", SCHEMAS, ids=lambda p: p.name)
def test_example_conforms(schema_path):
    example = load(EVENTS / "examples" / schema_path.name)
    errors = list(validator_for(schema_path).iter_errors(example))
    assert not errors, [e.message for e in errors]


@pytest.mark.parametrize("schema_path", SCHEMAS, ids=lambda p: p.name)
def test_schema_version_is_pinned_to_1(schema_path):
    example = copy.deepcopy(load(EVENTS / "examples" / schema_path.name))
    example["schema_version"] = 2
    assert not validator_for(schema_path).is_valid(example)


def test_bid_amount_must_be_a_decimal_string():
    validator = validator_for(EVENTS / "bid_accepted.v1.json")
    example = load(EVENTS / "examples" / "bid_accepted.v1.json")
    for bad in (1250.0, 1250, "1250", "1250.5", "-1.00"):
        assert not validator.is_valid({**example, "amount": bad}), bad


def test_bid_event_requires_the_partition_key_and_sequence():
    validator = validator_for(EVENTS / "bid_accepted.v1.json")
    example = load(EVENTS / "examples" / "bid_accepted.v1.json")
    for field in ("auction_id", "server_seq", "idempotency_key"):
        broken = {k: v for k, v in example.items() if k != field}
        assert not validator.is_valid(broken), field


def test_bid_event_rejects_unknown_fields():
    validator = validator_for(EVENTS / "bid_accepted.v1.json")
    example = load(EVENTS / "examples" / "bid_accepted.v1.json")
    assert not validator.is_valid({**example, "client_timestamp": "2026-08-20T10:00:00Z"})


def test_shill_alert_score_is_bounded():
    validator = validator_for(EVENTS / "shill_alert.v1.json")
    example = load(EVENTS / "examples" / "shill_alert.v1.json")
    assert not validator.is_valid({**example, "score": 1.2})
