"""The final rejection taxonomy (#21): code, contract and wire format agree.

1. :data:`app.errors.TAXONOMY` equals the published YAML (version, codes, HTTP statuses,
   retryability and ``details`` keys).
2. Every bid-path code is produced end to end through ``POST /auctions/{id}/bids`` and arrives
   in the uniform error envelope with exactly the published ``details`` keys.
"""

import pytest
import yaml

from app.errors import TAXONOMY, TAXONOMY_VERSION, BidRejected
from tests.fakes import AUCTION_ID, SELLER_ID
from tests.test_place_bid_api import CLOSED_BY_TIME, DRAFT_AUCTION, POOR, make_env
from zeo_common.contract_testing import assert_matches_contract, find_contracts_dir

PUBLISHED = yaml.safe_load(
    (find_contracts_dir() / "errors" / "bid-rejection-codes.yaml").read_text(encoding="utf-8")
)
BID_PATH = {entry["code"]: entry for entry in PUBLISHED["codes"] if entry["path"] == "bid"}


@pytest.fixture
def env():
    environment = make_env()
    with environment.client:
        yield environment


def test_version_and_status_are_published():
    assert PUBLISHED["version"] == TAXONOMY_VERSION
    assert PUBLISHED["status"] == "final"


def test_the_code_table_is_the_published_table():
    assert set(TAXONOMY) == set(BID_PATH)
    for code, entry in TAXONOMY.items():
        published = BID_PATH[code]
        assert (entry.http, entry.retryable, list(entry.details)) == (
            published["http"], published["retryable"], published["details"]), code


def test_only_state_unavailability_is_retryable():
    assert [code for code, entry in TAXONOMY.items() if entry.retryable] == [
        "AUCTION_STATE_UNAVAILABLE"]
    assert BidRejected("AUCTION_STATE_UNAVAILABLE", "down").retryable


def test_details_must_match_the_published_keys():
    with pytest.raises(ValueError, match="details"):
        BidRejected("BID_BELOW_INCREMENT", "too low")
    with pytest.raises(ValueError, match="details"):
        BidRejected("ACCOUNT_SUSPENDED", "no", {"why": "x"})


def reject(env, code):
    """Produce ``code`` through the API, the way a client would meet it."""
    if code == "ACCOUNT_SUSPENDED":
        return env.bid("100.00", suspended=True)
    if code == "SELF_BIDDING_FORBIDDEN":
        return env.bid("100.00", user=SELLER_ID)
    if code == "AUCTION_NOT_OPEN":
        return env.bid("100.00", auction=DRAFT_AUCTION)
    if code == "AUCTION_CLOSED":
        return env.bid("100.00", auction=CLOSED_BY_TIME)
    if code == "BID_BELOW_INCREMENT":
        return env.bid("1.00")
    if code == "INSUFFICIENT_FUNDS":
        return env.bid("100.00", user=POOR)
    if code == "AUCTION_STATE_UNAVAILABLE":
        env.orchestrator.failing = True
        return env.bid("100.00")
    raise AssertionError(code)


@pytest.mark.parametrize("code", sorted(set(BID_PATH) - {"DUPLICATE_IDEMPOTENCY_KEY"}))
def test_every_code_arrives_in_the_envelope_with_its_details(env, code):
    response = reject(env, code)
    assert response.status_code == BID_PATH[code]["http"], response.text
    body = response.json()
    assert body["code"] == code
    assert_matches_contract(body, "openapi/common.v1.yaml", "/components/schemas/Error")
    assert sorted(body["details"] or {}) == sorted(BID_PATH[code]["details"])
    assert env.publisher.events == []  # rejected before any state change


def test_duplicate_key_is_a_replay_not_an_error(env):
    headers = env.headers(key="key-replayed-0001")
    first = env.client.post(f"/api/v1/auctions/{AUCTION_ID}/bids", json={"amount": "100.00"},
                            headers=headers)
    again = env.client.post(f"/api/v1/auctions/{AUCTION_ID}/bids", json={"amount": "100.00"},
                            headers=headers)
    assert (first.status_code, again.status_code) == (202, BID_PATH[
        "DUPLICATE_IDEMPOTENCY_KEY"]["http"])
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json() == first.json()


def test_a_retryable_rejection_can_be_retried_with_the_same_key(env):
    env.orchestrator.failing = True
    headers = env.headers(key="key-retry-after-outage")
    down = env.client.post(f"/api/v1/auctions/{AUCTION_ID}/bids", json={"amount": "100.00"},
                           headers=headers)
    assert down.status_code == 503
    env.orchestrator.failing = False
    retried = env.client.post(f"/api/v1/auctions/{AUCTION_ID}/bids", json={"amount": "100.00"},
                              headers=headers)
    assert retried.status_code == 202
