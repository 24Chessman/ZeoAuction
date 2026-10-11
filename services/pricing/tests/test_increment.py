import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.increment import (
    DEFAULT_LADDER,
    IncrementRule,
    LadderError,
    band_for,
    min_increment,
    validate_ladder,
    velocity_factor,
)

LADDER_SQL = Path(__file__).resolve().parents[3] / "infra/postgres/init/51-pricing-dynamic.sql"


def D(value: str) -> Decimal:
    return Decimal(value)


@pytest.mark.parametrize(("price", "base"), [
    ("0.00", "1.00"), ("99.99", "1.00"), ("100.00", "5.00"), ("499.99", "5.00"),
    ("500.00", "10.00"), ("1000.00", "25.00"), ("4999.99", "25.00"), ("5000.00", "50.00"),
    ("250000.00", "50.00"),
])
def test_without_velocity_the_increment_is_the_band_base(price, base):
    assert min_increment(DEFAULT_LADDER, D(price), 0.0, 60) == D(base)


@pytest.mark.parametrize(("bpm", "expected"), [
    (0, "25.00"), (12, "30.00"), (30, "38.00"), (60, "50.00"), (600, "50.00"),
])
def test_velocity_scales_the_increment_up_to_the_multiplier(bpm, expected):
    # 25.00 * (1 + 1.0 * bpm/60): 30 -> 37.50, rounded half-up to whole rupees.
    assert min_increment(DEFAULT_LADDER, D("1200.00"), bpm, 60) == D(expected)


def test_the_increment_never_drops_below_the_base():
    for bpm in (0, 0.1, 1, 5, 29.9, 59, 61, 10_000):
        for rule in DEFAULT_LADDER:
            got = min_increment(DEFAULT_LADDER, rule.price_from, bpm, 60)
            assert got >= rule.base_increment


def test_the_increment_is_monotonic_in_velocity():
    previous = D("0")
    for bpm in range(0, 121, 3):
        got = min_increment(DEFAULT_LADDER, D("700.00"), bpm, 60)
        assert got >= previous
        previous = got


def test_rounding_keeps_whole_units_and_two_decimals():
    got = min_increment(DEFAULT_LADDER, D("50.00"), 30, 60)  # 1.00 * 1.5 -> 2
    assert got == D("2.00")
    assert str(got) == "2.00"


def test_velocity_factor_bounds():
    assert velocity_factor(-5, D("2"), 60) == 1
    assert velocity_factor(1e9, D("3"), 60) == 3
    with pytest.raises(ValueError):
        velocity_factor(1, D("2"), 0)


def test_negative_price_is_refused():
    with pytest.raises(ValueError):
        min_increment(DEFAULT_LADDER, D("-1.00"), 0, 60)


@pytest.mark.parametrize("rules", [
    (),
    (IncrementRule(D("1"), None, D("1"), D("1")),),
    (IncrementRule(D("0"), D("10"), D("1"), D("1")),),
    (IncrementRule(D("0"), D("10"), D("1"), D("1")), IncrementRule(D("20"), None, D("1"), D("1"))),
    (IncrementRule(D("0"), None, D("0"), D("1")),),
    (IncrementRule(D("0"), None, D("1"), D("0.5")),),
])
def test_invalid_ladders_are_refused(rules):
    with pytest.raises(LadderError):
        validate_ladder(rules)


def test_band_lookup_fails_outside_an_invalid_ladder():
    with pytest.raises(LadderError):
        band_for((IncrementRule(D("10"), D("20"), D("1"), D("1")),), D("5"))


def test_default_ladder_matches_the_sql_seed():
    """The in-memory ladder and 51-pricing-dynamic.sql must agree (and the bid service's
    fallback table is pinned to the same file, see services/bid/tests/test_ct3_breaker.py)."""
    rows = re.findall(
        r"\(([\d.]+),\s*([\d.]+|NULL),\s*([\d.]+),\s*([\d.]+)\)", LADDER_SQL.read_text())
    seeded = tuple(
        IncrementRule(D(a), None if b == "NULL" else D(b), D(c), D(m)) for a, b, c, m in rows)
    assert seeded == validate_ladder(DEFAULT_LADDER)
