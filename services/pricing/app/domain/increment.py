"""Dynamic minimum increment (#43, FR-PRICE-2, contract CT-3).

The increment scales with **price** and **velocity**:

1. the price band in the ladder (``pricing.increment_rules``) gives the base increment;
2. velocity raises it linearly from 1x (no recent bids) to the band's ``velocity_multiplier``
   at ``saturation_bpm`` bids per minute and above;
3. the result is rounded half-up to a whole currency unit and is never below the base.

**The base ladder is the floor the bid service relies on.** Bid Processing falls back to the same
ladder when CT-3 is down (``services/bid/app/adapters/pricing_client.py::INCREMENT_TIERS``),
and its replay (``app/domain/conflict.py::replay``, AC-04) re-derives the winner with that ladder.
Because the dynamic increment is never below the base, every bid accepted live also clears the
replay's floor, so replay names the same winner. Both ladders are pinned to
``infra/postgres/init/51-pricing-dynamic.sql`` by tests.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

UNIT = Decimal("1")


@dataclass(frozen=True)
class IncrementRule:
    price_from: Decimal
    price_to: Decimal | None  # None = no upper bound
    base_increment: Decimal
    velocity_multiplier: Decimal

    def covers(self, price: Decimal) -> bool:
        return price >= self.price_from and (self.price_to is None or price < self.price_to)


# Mirrors infra/postgres/init/51-pricing-dynamic.sql; used without a database (memory mode).
DEFAULT_LADDER: tuple[IncrementRule, ...] = (
    IncrementRule(Decimal("0.00"), Decimal("100.00"), Decimal("1.00"), Decimal("2.000")),
    IncrementRule(Decimal("100.00"), Decimal("500.00"), Decimal("5.00"), Decimal("2.000")),
    IncrementRule(Decimal("500.00"), Decimal("1000.00"), Decimal("10.00"), Decimal("2.000")),
    IncrementRule(Decimal("1000.00"), Decimal("5000.00"), Decimal("25.00"), Decimal("2.000")),
    IncrementRule(Decimal("5000.00"), None, Decimal("50.00"), Decimal("2.000")),
)


class LadderError(ValueError):
    pass


def validate_ladder(rules: tuple[IncrementRule, ...]) -> tuple[IncrementRule, ...]:
    """Bands must start at 0, be contiguous, end unbounded, and only grow the increment."""
    ordered = tuple(sorted(rules, key=lambda r: r.price_from))
    if not ordered or ordered[0].price_from != 0:
        raise LadderError("the ladder must start at 0.00")
    if ordered[-1].price_to is not None:
        raise LadderError("the last band must have no upper bound")
    for previous, rule in zip(ordered, ordered[1:], strict=False):
        if previous.price_to != rule.price_from:
            raise LadderError(f"gap or overlap at {rule.price_from}")
    for rule in ordered:
        if rule.base_increment <= 0 or rule.velocity_multiplier < 1:
            raise LadderError(f"invalid band starting at {rule.price_from}")
    return ordered


def band_for(ladder: tuple[IncrementRule, ...], price: Decimal) -> IncrementRule:
    for rule in ladder:
        if rule.covers(price):
            return rule
    raise LadderError(f"no band covers {price}")


def velocity_factor(bids_per_minute: float, max_multiplier: Decimal,
                    saturation_bpm: float) -> Decimal:
    if saturation_bpm <= 0:
        raise ValueError("saturation_bpm must be positive")
    share = Decimal(str(min(max(bids_per_minute, 0.0), saturation_bpm) / saturation_bpm))
    return Decimal(1) + (max_multiplier - 1) * share


def min_increment(ladder: tuple[IncrementRule, ...], current_price: Decimal,
                  bids_per_minute: float, saturation_bpm: float) -> Decimal:
    if current_price < 0:
        raise ValueError("current_price must not be negative")
    rule = band_for(ladder, current_price)
    scaled = rule.base_increment * velocity_factor(
        bids_per_minute, rule.velocity_multiplier, saturation_bpm)
    rounded = scaled.quantize(UNIT, rounding=ROUND_HALF_UP)
    return max(rounded, rule.base_increment).quantize(Decimal("0.01"))
