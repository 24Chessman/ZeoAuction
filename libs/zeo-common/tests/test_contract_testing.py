import pytest
from jsonschema import ValidationError

from zeo_common.contract_testing import assert_matches_contract, contract_schema

AUCTION_STATE = ("openapi/internal/auction-state.v1.yaml", "/components/schemas/AuctionState")


def valid_state() -> dict:
    return {
        "auction_id": "00000000-0000-4000-8000-000000000201",
        "seller_id": "00000000-0000-4000-8000-000000000002",
        "state": "OPEN",
        "bid_permitted": True,
        "currency": "USD",
        "starting_price": "100.00",
        "closes_at": None,
        "as_of": "2026-08-20T10:15:30Z",
    }


def test_refs_into_other_files_are_inlined():
    schema = contract_schema(*AUCTION_STATE)
    assert schema["properties"]["currency"]["pattern"] == "^[A-Z]{3}$"
    assert "$ref" not in str(schema)


def test_valid_payload_passes():
    assert_matches_contract(valid_state(), *AUCTION_STATE)


def test_float_money_is_rejected():
    payload = valid_state() | {"starting_price": 100.0}
    with pytest.raises(ValidationError):
        assert_matches_contract(payload, *AUCTION_STATE)


def test_unknown_fields_are_rejected_when_the_contract_is_closed():
    with pytest.raises(ValidationError):
        assert_matches_contract(valid_state() | {"extra": 1}, *AUCTION_STATE)


def test_event_schemas_load_from_json():
    schema = contract_schema("events/bid_accepted.v1.json")
    assert schema["properties"]["schema_version"] == {"const": 1}
