"""Published OpenAPI contracts are valid, and the bid contract matches the rejection taxonomy."""

import pytest
import yaml
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

from .conftest import CONTRACTS

SPECS = sorted((CONTRACTS / "openapi").rglob("*.yaml"))
BID_SPEC = CONTRACTS / "openapi" / "bid-service.v1.yaml"


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: p.relative_to(CONTRACTS).as_posix())
def test_spec_is_valid_openapi_31(spec_path):
    spec, base_uri = read_from_filename(str(spec_path))
    assert spec["openapi"].startswith("3.1")
    validate(spec, base_uri=base_uri)


def test_bid_operations_are_published():
    operation_ids = {
        op["operationId"]
        for path in load_yaml(BID_SPEC)["paths"].values()
        for method, op in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operation_ids == {"placeBid", "listBids", "getBid"}


def test_place_bid_requires_idempotency_key():
    post = load_yaml(BID_SPEC)["paths"]["/auctions/{auctionId}/bids"]["post"]
    refs = [p.get("$ref", "") for p in post["parameters"]]
    assert any(ref.endswith("/IdempotencyKey") for ref in refs)


def test_every_bid_rejection_code_is_documented_at_its_status():
    spec = load_yaml(BID_SPEC)
    post = spec["paths"]["/auctions/{auctionId}/bids"]["post"]
    codes = load_yaml(CONTRACTS / "errors" / "bid-rejection-codes.yaml")["codes"]

    def description_for(status: str) -> str:
        response = post["responses"][status]
        if "$ref" in response and response["$ref"].startswith("#/"):
            name = response["$ref"].rsplit("/", 1)[-1]
            response = spec["components"]["responses"][name]
        return response["description"]

    for entry in codes:
        if entry["path"] != "bid":
            continue
        status = str(entry["http"])
        assert status in post["responses"], f"{entry['code']}: no {status} response"
        documented = description_for(status)
        assert entry["code"] in documented, f"{entry['code']} not documented on {status}"


def test_rejection_codes_are_unique_and_upper_snake():
    taxonomy = load_yaml(CONTRACTS / "errors" / "bid-rejection-codes.yaml")
    codes = [c["code"] for c in taxonomy["codes"]]
    assert len(codes) == len(set(codes))
    assert all(c.isupper() and " " not in c for c in codes)


def test_auction_state_contract_pins_bid_permitting_states():
    spec = load_yaml(CONTRACTS / "openapi" / "internal" / "auction-state.v1.yaml")
    state = spec["components"]["schemas"]["AuctionState"]
    assert "OPEN" in state["properties"]["state"]["enum"]
    assert "EXTENDED" in state["properties"]["state"]["enum"]
    assert "OPEN or EXTENDED" in state["properties"]["bid_permitted"]["description"]


def test_money_is_a_string_everywhere_in_the_pricing_contract():
    spec = load_yaml(CONTRACTS / "openapi" / "internal" / "pricing.v1.yaml")
    props = spec["components"]["schemas"]["MinIncrement"]["properties"]
    for field in ("min_increment", "min_next_bid"):
        assert props[field]["$ref"].endswith("/Money")
