"""Parameterised shill-ring behaviour for the synthetic dataset (#51, ADR-0008).

A ring is a set of accounts controlled by one seller that bids up that seller's auctions and
drops out before winning. Each ring draws its behaviour from four independent signals, so
recall and precision can later be measured per signal (SDD section 10):

* **seller-linked accounts**: ring accounts bid only on their seller's auctions;
* **shared fingerprints**: ring accounts reuse a small set of device fingerprints;
* **bid velocity**: shill bids come in fast bursts;
* **inter-arrival regularity**: the gaps between shill bids are machine-regular.

Honest traffic deliberately contains look-alikes (households sharing a device, loyal buyers
of one seller, fast end-of-auction bidding wars), so a detector cannot score well by
flagging any single signal.
"""

import random
from dataclasses import dataclass
from decimal import Decimal

# Same tier table as the bid service's CT-3 stub (services/bid/app/adapters/pricing_client.py),
# so the synthetic log obeys the same increment rule as live traffic.
INCREMENT_TIERS: tuple[tuple[Decimal | None, Decimal], ...] = (
    (Decimal("100.00"), Decimal("1.00")),
    (Decimal("500.00"), Decimal("5.00")),
    (Decimal("1000.00"), Decimal("10.00")),
    (Decimal("5000.00"), Decimal("25.00")),
    (None, Decimal("50.00")),
)


def increment_for(price: Decimal) -> Decimal:
    for upper, increment in INCREMENT_TIERS:
        if upper is None or price < upper:
            return increment
    raise AssertionError("unreachable")


SIGNALS = ("seller_linked", "shared_fingerprint", "high_velocity", "regular_interarrival")


@dataclass(frozen=True)
class RingPattern:
    size: int  # shill accounts in the ring
    auctions: int  # how many of the seller's auctions the ring works
    seller_linked: bool  # accounts never bid outside the seller's auctions
    fingerprints: int  # distinct device fingerprints across the ring (1 = all share one)
    bids_per_minute: float  # burst velocity
    interarrival_cv: float  # coefficient of variation of gaps; low = regular
    push_fraction: float  # how far towards the honest valuation the ring drives the price
    stop_before_close: float  # fraction of the auction left when the ring stops bidding

    @property
    def signals(self) -> tuple[str, ...]:
        flags = []
        if self.seller_linked:
            flags.append("seller_linked")
        if self.fingerprints < self.size:
            flags.append("shared_fingerprint")
        if self.bids_per_minute >= 2.0:
            flags.append("high_velocity")
        if self.interarrival_cv <= 0.25:
            flags.append("regular_interarrival")
        return tuple(flags)


def sample_ring_pattern(rng: random.Random) -> RingPattern:
    """Each signal is present with its own probability; every ring shows at least one."""
    while True:
        size = rng.randint(2, 5)
        pattern = RingPattern(
            size=size,
            auctions=1 if rng.random() < 0.7 else 2,
            seller_linked=rng.random() < 0.65,
            fingerprints=rng.randint(1, max(1, size - 1)) if rng.random() < 0.55 else size,
            bids_per_minute=round(rng.uniform(2.0, 6.0) if rng.random() < 0.6
                                  else rng.uniform(0.2, 1.2), 3),
            interarrival_cv=round(rng.uniform(0.05, 0.25) if rng.random() < 0.5
                                  else rng.uniform(0.6, 1.2), 3),
            push_fraction=round(rng.uniform(0.55, 0.9), 3),
            stop_before_close=round(rng.uniform(0.12, 0.35), 3),
        )
        if pattern.signals:
            return pattern
