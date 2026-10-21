"""In-flight shill scoring over the per-auction window (#53, SDD 5.4.1-5.4.2).

Every accepted bid is scored the moment it is consumed: the bidder's signals
(:mod:`app.signals`) are combined into one weighted average on 0..1, and a bidder at or above
the threshold becomes a **suspect** in that auction. :class:`ShillDetector` keeps the suspects
per auction and asks for an alert each time a new one appears, so an auction gets its first
alert on the bid that tips it, long before it closes, and a ring that grows is reported again.

v1 weights come from ``eval/quick_eval.py`` on the labelled dataset and were checked on two
held-out seeds (``docs/fraud/v1-measurement.md``). Seller-linked bidding counts double; bid
velocity and in-auction device overlap corroborate it, so seller links alone (score 0.5) never
reach the threshold: loyal buyers and brand-new honest accounts look seller-linked too. The
other four SDD signals are computed and reported as evidence, but weigh nothing in v1: none
improved recall or precision on the dataset. Tuning them is Plan 6 (#55-#57).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.features import BidderFeatures
from app.signals import SIGNAL_NAMES, Signals

DETECTOR_VERSION = "shill-v1"
V1_WEIGHTS: Mapping[str, float] = {
    "bidVelocity": 1.0,
    "selfBidRatio": 2.0,
    "interArrivalStdDev": 0.0,
    "fingerprintOverlap": 1.0,
    "accountAgeDays": 0.0,
    "winRateWithSeller": 0.0,
    "graphDegreeToSeller": 0.0,
}
V1_THRESHOLD = 0.6


@dataclass(frozen=True)
class Score:
    features: BidderFeatures
    signals: Signals
    value: float  # 0..1, four decimals (fraud.fraud_alerts.score is numeric(5, 4))
    suspect: bool


class ShillScorer:
    def __init__(self, weights: Mapping[str, float] = V1_WEIGHTS,
                 threshold: float = V1_THRESHOLD) -> None:
        unknown = set(weights) - set(SIGNAL_NAMES)
        if unknown:
            raise ValueError(f"unknown signals: {sorted(unknown)}")
        if any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError("weights must be non-negative and not all zero")
        if not 0 < threshold <= 1:
            raise ValueError("threshold must be in (0, 1]")
        self.weights = dict(weights)
        self.threshold = threshold

    def score(self, features: BidderFeatures) -> Score:
        signals = Signals.from_features(features)
        strengths = signals.strengths()
        total = sum(self.weights.values())
        value = round(sum(w * strengths[name] for name, w in self.weights.items()) / total, 4)
        return Score(features, signals, value, value >= self.threshold)


@dataclass(frozen=True)
class AlertDecision:
    """An auction just gained a suspect: what the alert publisher needs."""

    auction_id: str
    trigger: Score  # the bid that tipped it
    suspects: tuple[str, ...]  # every suspect in the auction so far, in the order found
    score: float  # the highest suspect score in the auction
    auction_closes_at: datetime | None
    observed_at: datetime | None


@dataclass
class _AuctionSuspects:
    scores: dict[str, float] = field(default_factory=dict)


class ShillDetector:
    def __init__(self, scorer: ShillScorer | None = None) -> None:
        self.scorer = scorer or ShillScorer()
        self._auctions: dict[str, _AuctionSuspects] = {}

    def observe(self, features: BidderFeatures) -> AlertDecision | None:
        score = self.scorer.score(features)
        if not score.suspect:
            return None
        suspects = self._auctions.setdefault(features.auction_id, _AuctionSuspects()).scores
        known = features.bidder_id in suspects
        suspects[features.bidder_id] = max(score.value, suspects.get(features.bidder_id, 0.0))
        if known:
            return None
        return AlertDecision(
            auction_id=features.auction_id,
            trigger=score,
            suspects=tuple(suspects),
            score=max(suspects.values()),
            auction_closes_at=features.auction_closes_at,
            observed_at=features.observed_at,
        )

    def suspects(self, auction_id: str) -> dict[str, float]:
        found = self._auctions.get(auction_id)
        return dict(found.scores) if found else {}

    def forget_auction(self, auction_id: str) -> None:
        self._auctions.pop(auction_id, None)
