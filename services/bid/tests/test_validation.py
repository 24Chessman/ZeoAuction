from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
import yaml

from app.adapters.funds import StubFunds
from app.domain.validation import BidFacts, minimum_next_bid, validate_bid
from app.errors import REJECTION_STATUS, BidRejected
from zeo_common.contract_testing import find_contracts_dir

SELLER = uuid4()
BIDDER = uuid4()

VALID = BidFacts(
    bidder_id=BIDDER,
    bidder_suspended=False,
    seller_id=SELLER,
    auction_state="OPEN",
    bid_permitted=True,
    amount=Decimal("125.00"),
    min_next_bid=Decimal("125.00"),
    available_funds=Decimal("1000.00"),
)


def rejection(facts: BidFacts) -> BidRejected:
    with pytest.raises(BidRejected) as caught:
        validate_bid(facts)
    return caught.value


def test_a_valid_bid_passes():
    validate_bid(VALID)
    validate_bid(replace(VALID, auction_state="EXTENDED"))


def test_suspended_account():
    error = rejection(replace(VALID, bidder_suspended=True))
    assert (error.code, error.status_code) == ("ACCOUNT_SUSPENDED", 403)


def test_seller_cannot_bid_on_own_auction():
    error = rejection(replace(VALID, bidder_id=SELLER))
    assert (error.code, error.status_code) == ("SELF_BIDDING_FORBIDDEN", 403)


@pytest.mark.parametrize(
    "state", ["DRAFT", "SCHEDULED", "CLOSING", "CLOSED", "SETTLED", "CANCELLED"]
)
def test_auction_must_be_open_or_extended(state):
    error = rejection(replace(VALID, auction_state=state, bid_permitted=False))
    assert (error.code, error.status_code) == ("AUCTION_NOT_OPEN", 409)
    assert error.details == {"state": state}


def test_bid_below_increment_reports_the_minimum():
    error = rejection(replace(VALID, amount=Decimal("124.99")))
    assert (error.code, error.status_code) == ("BID_BELOW_INCREMENT", 422)
    assert error.details == {"min_next_bid": "125.00"}
    assert error.message == "Minimum next bid is 125.00"


def test_insufficient_funds():
    error = rejection(replace(VALID, available_funds=Decimal("124.99")))
    assert (error.code, error.status_code) == ("INSUFFICIENT_FUNDS", 402)


def test_a_bid_failing_every_rule_gets_the_first_code_in_order():
    everything_wrong = replace(
        VALID, bidder_suspended=True, bidder_id=SELLER, bid_permitted=False,
        auction_state="CLOSED", amount=Decimal("1.00"), available_funds=Decimal("0.00"),
    )
    assert rejection(everything_wrong).code == "ACCOUNT_SUSPENDED"
    assert rejection(replace(everything_wrong, bidder_suspended=False)).code == (
        "SELF_BIDDING_FORBIDDEN")
    assert rejection(replace(everything_wrong, bidder_suspended=False, bidder_id=BIDDER)).code == (
        "AUCTION_NOT_OPEN")
    assert rejection(replace(VALID, amount=Decimal("1.00"),
                             available_funds=Decimal("0.00"))).code == "BID_BELOW_INCREMENT"


def test_first_bid_may_equal_the_starting_price():
    assert minimum_next_bid(None, Decimal("100.00"), Decimal("5.00")) == Decimal("100.00")
    assert minimum_next_bid(Decimal("120.00"), Decimal("100.00"), Decimal("5.00")) == Decimal(
        "125.00")


def test_unknown_codes_cannot_be_raised():
    with pytest.raises(ValueError, match="taxonomy"):
        BidRejected("BID_TOO_LOW", "no")


def test_taxonomy_matches_the_published_contract():
    published = yaml.safe_load(
        (find_contracts_dir() / "errors" / "bid-rejection-codes.yaml").read_text()
    )
    bid_path = {c["code"]: c["http"] for c in published["codes"] if c["path"] == "bid"}
    assert bid_path == REJECTION_STATUS


def test_rejection_converts_to_the_error_envelope():
    error = BidRejected("BID_BELOW_INCREMENT", "Minimum next bid is 5.00", {"min_next_bid": "5.00"})
    api_error = error.to_api_error()
    assert (api_error.code, api_error.status_code, api_error.details) == (
        "BID_BELOW_INCREMENT", 422, {"min_next_bid": "5.00"})


async def test_stub_funds_uses_the_configured_limit():
    assert await StubFunds(Decimal("500.00")).available(uuid4()) == Decimal("500.00")
