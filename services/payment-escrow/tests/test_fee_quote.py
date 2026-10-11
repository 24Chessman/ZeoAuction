"""GET /fees/quote: the flat fee disclosed before a bid (FR-PAY-3, AC-07)."""

from decimal import Decimal

import pytest
import yaml
from fastapi.testclient import TestClient

from app.fees import ACTIVE_FEE, quote
from app.main import app
from zeo_common.contract_testing import find_contracts_dir

client = TestClient(app)


def test_quote_adds_the_flat_fee():
    response = client.get("/api/v1/fees/quote", params={"bid_amount": "1250.00"})
    assert response.status_code == 200
    assert response.json() == {
        "bid_amount": "1250.00", "convenience_fee": "25.00", "total": "1275.00",
        "currency": "USD", "fee_version": "2026-08-v1",
    }
    assert response.headers["cache-control"] == "public, max-age=60"


def test_the_fee_is_flat_not_a_percentage():
    small = quote(Decimal("10.00"))
    large = quote(Decimal("99999.00"))
    assert small.convenience_fee == large.convenience_fee == Decimal("25.00")


@pytest.mark.parametrize("amount", ["1250", "12.5", "-5.00", "1e3", "abc", "1250.000"])
def test_amounts_must_be_two_decimal_strings(amount):
    response = client.get("/api/v1/fees/quote", params={"bid_amount": amount})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_zero_is_refused():
    response = client.get("/api/v1/fees/quote", params={"bid_amount": "0.00"})
    assert response.status_code == 422
    assert response.json()["details"] == {"field": "bid_amount"}


def test_the_quote_needs_no_token():
    assert client.get("/api/v1/fees/quote", params={"bid_amount": "1.00"}).status_code == 200


def test_the_stub_matches_the_settlement_policy():
    policy_path = find_contracts_dir().parent / "config" / "settlement-policy.yaml"
    fee = yaml.safe_load(policy_path.read_text(encoding="utf-8"))["convenience_fee"]
    assert (fee["fee_version"], Decimal(fee["amount"]), fee["currency"]) == (
        ACTIVE_FEE.fee_version, ACTIVE_FEE.convenience_fee, ACTIVE_FEE.currency)
