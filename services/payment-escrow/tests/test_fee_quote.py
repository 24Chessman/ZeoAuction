"""GET /fees/quote: the flat fee disclosed before a bid (FR-PAY-3, AC-07)."""

from decimal import Decimal

import pytest
import yaml

from app.domain.fees import ACTIVE_FEE, FeeConfig, FeeError, quote
from zeo_common.contract_testing import assert_matches_contract, find_contracts_dir


def test_quote_adds_the_flat_fee(harness):
    response = harness.client.get("/api/v1/fees/quote", params={"bid_amount": "1250.00"})
    assert response.status_code == 200
    assert response.json() == {
        "bid_amount": "1250.00", "convenience_fee": "99.00", "total": "1349.00",
        "currency": "INR", "fee_version": "2026-10-v1",
    }
    assert response.headers["cache-control"] == "public, max-age=60"
    assert_matches_contract(response.json(), "openapi/payment.v1.yaml",
                            "/components/schemas/FeeQuote")


def test_the_quote_reads_the_active_fee_config(harness):
    harness.repo.fee = FeeConfig("2027-01-v2", Decimal("149.00"), "INR")
    body = harness.client.get("/api/v1/fees/quote", params={"bid_amount": "1.00"}).json()
    assert (body["convenience_fee"], body["total"], body["fee_version"]) == (
        "149.00", "150.00", "2027-01-v2")


def test_the_fee_is_flat_not_a_percentage():
    small = quote(Decimal("10.00"))
    large = quote(Decimal("99999.00"))
    assert small.convenience_fee == large.convenience_fee == Decimal("99.00")


def test_floats_and_non_positive_amounts_are_refused():
    for amount in (Decimal("0"), Decimal("-1.00"), 10.0):
        with pytest.raises(FeeError):
            quote(amount)


@pytest.mark.parametrize("amount", ["1250", "12.5", "-5.00", "1e3", "abc", "1250.000"])
def test_amounts_must_be_two_decimal_strings(harness, amount):
    response = harness.client.get("/api/v1/fees/quote", params={"bid_amount": amount})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_zero_is_refused(harness):
    response = harness.client.get("/api/v1/fees/quote", params={"bid_amount": "0.00"})
    assert response.status_code == 422
    assert response.json()["details"] == {"field": "bid_amount"}


def test_the_default_fee_matches_the_settlement_policy():
    policy_path = find_contracts_dir().parent / "config" / "settlement-policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    fee = policy["convenience_fee"]
    assert (fee["fee_version"], Decimal(fee["amount"]), fee["currency"]) == (
        ACTIVE_FEE.fee_version, ACTIVE_FEE.convenience_fee, ACTIVE_FEE.currency)
    assert policy["protection_window"]["days"] == ACTIVE_FEE.protection_window_days
