from decimal import Decimal

import pytest

from zeo_common import MoneyError, format_money, parse_money


@pytest.mark.parametrize("value", ["0.00", "1250.00", "25.50", "9999999999.99"])
def test_parse_accepts_contract_money_strings(value):
    assert parse_money(value) == Decimal(value)


@pytest.mark.parametrize(
    "value",
    ["1250", "1250.0", "1250.000", "-1.00", "01.00", "1,250.00", "", " 1.00", "1e3", "NaN"],
)
def test_parse_rejects_malformed_strings(value):
    with pytest.raises(MoneyError):
        parse_money(value)


@pytest.mark.parametrize("value", [1250.0, 1250, Decimal("1250.00"), None])
def test_parse_rejects_non_strings(value):
    with pytest.raises(MoneyError):
        parse_money(value)


def test_format_rounds_half_even_to_cents():
    assert format_money(Decimal("1250")) == "1250.00"
    assert format_money(Decimal("0.125")) == "0.12"
    assert format_money(Decimal("0.135")) == "0.14"


def test_format_rejects_floats():
    with pytest.raises(MoneyError):
        format_money(0.1)


def test_round_trip():
    assert format_money(parse_money("1275.00")) == "1275.00"
