"""The seven shill signals of SDD Table 5.3, by their contract names (``ShillAlert v1``
``signals``), built from one bidder's :class:`app.features.BidderFeatures`.

:class:`Signals` carries the raw values, which go into the alert as evidence. :meth:`strengths`
maps each onto 0..1 (1 = looks like a shill) for the scorer; the mapping for every signal lives
here, so the scorer is only weights and a threshold.
"""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # app.features imports app.signals.fingerprint, so not at run time
    from app.features import BidderFeatures

SIGNAL_NAMES = ("bidVelocity", "selfBidRatio", "interArrivalStdDev", "fingerprintOverlap",
                "accountAgeDays", "winRateWithSeller", "graphDegreeToSeller")

# Honest bids in the dataset are hours apart; a bidder keeping up one bid every 20 minutes in
# one auction (0.05 per minute) is already unusual, and one every 10 minutes is a burst.
VELOCITY_MIDPOINT = 0.05
VELOCITY_SCALE = 0.02
# Accounts seen for less than this many days count as new.
NEW_ACCOUNT_DAYS = 7.0


@dataclass(frozen=True)
class Signals:
    bid_velocity: float  # bids per minute in this auction
    self_bid_ratio: float  # share of the bidder's bids that were on this seller
    inter_arrival_cv: float | None  # gap regularity (coefficient of variation)
    inter_arrival_stdev: float | None  # seconds
    fingerprint_overlap: int  # other accounts on this bidder's device in this auction
    account_age_days: float
    win_rate_with_seller: float | None
    graph_degree_to_seller: int  # distinct sellers the bidder has bid with
    bids_in_auction: int

    @classmethod
    def from_features(cls, features: "BidderFeatures") -> "Signals":
        return cls(
            bid_velocity=features.bids_per_minute,
            self_bid_ratio=features.seller_link_ratio,
            inter_arrival_cv=features.interarrival_cv,
            inter_arrival_stdev=features.interarrival_stdev,
            fingerprint_overlap=features.fingerprint_overlap,
            account_age_days=features.account_age_days,
            win_rate_with_seller=features.win_rate_with_seller,
            graph_degree_to_seller=features.sellers_bid_with,
            bids_in_auction=features.bids_in_auction,
        )

    def strengths(self) -> dict[str, float]:
        """Each signal on 0..1, keyed by its contract name."""
        return {
            # One bid has no rate; the logistic keeps a single fast pair from saturating.
            "bidVelocity": (_logistic(self.bid_velocity, VELOCITY_MIDPOINT, VELOCITY_SCALE)
                            if self.bids_in_auction >= 2 else 0.0),
            "selfBidRatio": self.self_bid_ratio,
            "interArrivalStdDev": (1.0 - min(self.inter_arrival_cv, 1.0)
                                   if self.inter_arrival_cv is not None else 0.0),
            "fingerprintOverlap": min(self.fingerprint_overlap, 1),
            "accountAgeDays": max(0.0, 1.0 - self.account_age_days / NEW_ACCOUNT_DAYS),
            "winRateWithSeller": (1.0 - self.win_rate_with_seller
                                  if self.win_rate_with_seller is not None else 0.0),
            "graphDegreeToSeller": 1.0 / self.graph_degree_to_seller,
        }

    def evidence(self) -> dict[str, float]:
        """The raw values for the alert's ``signals`` object (unknown ones left out)."""
        values: dict[str, float | None] = {
            "bidVelocity": round(self.bid_velocity, 4),
            "selfBidRatio": round(self.self_bid_ratio, 4),
            "interArrivalStdDev": (round(self.inter_arrival_stdev, 3)
                                   if self.inter_arrival_stdev is not None else None),
            "fingerprintOverlap": self.fingerprint_overlap,
            "accountAgeDays": round(self.account_age_days, 3),
            "winRateWithSeller": (round(self.win_rate_with_seller, 4)
                                  if self.win_rate_with_seller is not None else None),
            "graphDegreeToSeller": self.graph_degree_to_seller,
        }
        return {name: value for name, value in values.items() if value is not None}


def _logistic(value: float, midpoint: float, scale: float) -> float:
    exponent = -(value - midpoint) / scale
    if exponent > 700:  # math.exp overflows past ~709
        return 0.0
    return 1.0 / (1.0 + math.exp(exponent))
