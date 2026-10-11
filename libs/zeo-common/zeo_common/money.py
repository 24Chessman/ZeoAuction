"""Money is a decimal string with exactly two places on every boundary, never a float.

The same pattern is published as ``Money`` in ``contracts/openapi/common.v1.yaml``.
"""

import re
from decimal import ROUND_HALF_EVEN, Decimal

MONEY_PATTERN = r"^(0|[1-9]\d{0,9})\.\d{2}$"
_MONEY_RE = re.compile(MONEY_PATTERN)
_QUANTUM = Decimal("0.01")


class MoneyError(ValueError):
    pass


def parse_money(value: str) -> Decimal:
    """Parse a contract money string such as ``"1250.00"``. Floats are rejected outright."""
    if not isinstance(value, str):
        raise MoneyError(f"money must be a decimal string, got {type(value).__name__}")
    if not _MONEY_RE.match(value):
        raise MoneyError(f"invalid money string: {value!r}")
    return Decimal(value)


def format_money(amount: Decimal) -> str:
    """Render a Decimal as a contract money string, rounding half-even to cents."""
    if not isinstance(amount, Decimal):
        raise MoneyError(f"amount must be a Decimal, got {type(amount).__name__}")
    return str(amount.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN))
