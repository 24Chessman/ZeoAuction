"""Flat convenience fee and the pre-bid quote (FR-PAY-3, SDD 7.4, AC-07).

Plan 3 stub (backs #70): the quote answers from the fixed ``fee_config`` that Plan 1 seeded
(config/settlement-policy.yaml, ADR-0011). The fee engine (Plan 4) reads the active
``payment.fee_config`` row instead; the response shape and the values do not change, because
disclosure, invoice and settlement must never disagree. The fee is a flat amount per
completed sale, never a percentage, and losing bidders are never charged.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FeeConfig:
    fee_version: str
    convenience_fee: Decimal
    currency: str


# Must equal config/settlement-policy.yaml and the seed in infra/postgres/init/60-payment.sql
# (tests/test_fee_quote.py and tests/contracts/test_settlement_policy.py check both).
ACTIVE_FEE = FeeConfig(fee_version="2026-08-v1", convenience_fee=Decimal("25.00"),
                       currency="USD")


@dataclass(frozen=True)
class FeeQuote:
    bid_amount: Decimal
    convenience_fee: Decimal
    total: Decimal
    currency: str
    fee_version: str


def quote(bid_amount: Decimal, config: FeeConfig = ACTIVE_FEE) -> FeeQuote:
    if bid_amount <= 0:
        raise ValueError("bid_amount must be positive")
    return FeeQuote(
        bid_amount=bid_amount,
        convenience_fee=config.convenience_fee,
        total=bid_amount + config.convenience_fee,
        currency=config.currency,
        fee_version=config.fee_version,
    )
