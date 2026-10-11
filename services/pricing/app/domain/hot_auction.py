"""Hot-auction flagging (#44, FR-PRICE-3).

An auction is *hot* (contended) when its velocity reaches ``enter_bpm``; it stays hot until the
velocity falls below ``exit_bpm``. The gap between the two (hysteresis) stops a flag flapping on
and off around a single threshold. The flag is exposed on CT-3 and ``/velocity`` for prioritised
buffering and monitoring, and every change is persisted to ``pricing.hot_auction_flags``.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Change(Enum):
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


@dataclass(frozen=True)
class HotPolicy:
    enter_bpm: float = 30.0
    exit_bpm: float = 15.0

    def __post_init__(self) -> None:
        if not 0 < self.exit_bpm <= self.enter_bpm:
            raise ValueError("need 0 < exit_bpm <= enter_bpm")


@dataclass(frozen=True)
class Transition:
    auction_id: str
    change: Change
    bids_per_minute: float
    at: datetime
    reason: str


class HotAuctions:
    def __init__(self, policy: HotPolicy) -> None:
        self.policy = policy
        self._hot: set[str] = set()

    def is_hot(self, auction_id: str) -> bool:
        return auction_id in self._hot

    def count(self) -> int:
        return len(self._hot)

    def restore(self, auction_ids: list[str]) -> None:
        self._hot.update(auction_ids)

    def evaluate(self, auction_id: str, bids_per_minute: float,
                 at: datetime) -> Transition | None:
        """Apply the thresholds; returns the change, if there was one."""
        hot = auction_id in self._hot
        if not hot and bids_per_minute >= self.policy.enter_bpm:
            self._hot.add(auction_id)
            return Transition(auction_id, Change.FLAGGED, bids_per_minute, at,
                              f"velocity {bids_per_minute:.1f} bids/min >= "
                              f"{self.policy.enter_bpm:g}")
        if hot and bids_per_minute < self.policy.exit_bpm:
            self._hot.discard(auction_id)
            return Transition(auction_id, Change.CLEARED, bids_per_minute, at,
                              f"velocity {bids_per_minute:.1f} bids/min < "
                              f"{self.policy.exit_bpm:g}")
        return None
