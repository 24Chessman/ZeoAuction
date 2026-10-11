"""Flat convenience-fee engine and the pre-bid quote (#61, FR-PAY-3, SDD 7.4, AC-07).

The fee is a flat amount per completed sale, never a percentage, and losing bidders are never
charged. Exactly one ``payment.fee_config`` row is active at a time; the quote, the invoice and
the ledger all read that row and carry its ``fee_version``, so what a bidder is shown before
bidding is what the winner is invoiced (the quote is not an estimate).
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FeeConfig:
    fee_version: str
    convenience_fee: Decimal
    currency: str
    protection_window_days: int = 7


# The row seeded by infra/postgres/init/61-payment-razorpay.sql from config/settlement-policy.yaml
# (ADR-0009, ADR-0011). Used when the service runs without a database; tests/test_fees.py and
# tests/contracts/test_settlement_policy.py keep the three identical.
ACTIVE_FEE = FeeConfig(fee_version="2026-10-v1", convenience_fee=Decimal("99.00"),
                       currency="INR", protection_window_days=7)


class FeeError(ValueError):
    pass


@dataclass(frozen=True)
class FeeQuote:
    bid_amount: Decimal
    convenience_fee: Decimal
    total: Decimal
    currency: str
    fee_version: str


def quote(bid_amount: Decimal, config: FeeConfig = ACTIVE_FEE) -> FeeQuote:
    if not isinstance(bid_amount, Decimal) or bid_amount <= 0:
        raise FeeError("bid_amount must be positive")
    return FeeQuote(
        bid_amount=bid_amount,
        convenience_fee=config.convenience_fee,
        total=bid_amount + config.convenience_fee,
        currency=config.currency,
        fee_version=config.fee_version,
    )
