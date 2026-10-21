"""Glue between the consumer's ``on_features`` hook, the shill detector and the alert publisher.

Live, an alert's ``raised_at`` is the wall clock. Replaying history (``eval/quick_eval.py``)
sets ``replay_time``, so ``raised_at`` is the time of the bid that tipped the alert: the moment
the detector would have raised it had the bids arrived live. That keeps "before close" (AC-14)
meaningful for a dataset whose auctions closed weeks ago.
"""

from app.alerts import AlertOutcome, AlertPublisher
from app.features import BidderFeatures
from app.scorer import ShillDetector


class ScoringPipeline:
    def __init__(self, detector: ShillDetector, publisher: AlertPublisher, *,
                 replay_time: bool = False) -> None:
        self.detector = detector
        self.publisher = publisher
        self.replay_time = replay_time

    async def __call__(self, features: BidderFeatures) -> AlertOutcome | None:
        decision = self.detector.observe(features)
        if decision is None:
            return None
        raised_at = decision.observed_at if self.replay_time else None
        return await self.publisher.publish(decision, raised_at)

    def forget_auction(self, auction_id: str) -> None:
        self.detector.forget_auction(auction_id)
