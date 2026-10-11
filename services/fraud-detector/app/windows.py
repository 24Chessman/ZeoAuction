"""Per-auction sliding windows over ``bid.events`` (#52, SDD 5.4).

``bid.events`` is keyed by ``auction_id``, so one partition delivers an auction's bids in
``server_seq`` order and the detector never re-sorts. A ``server_seq`` at or below the last one
seen is a redelivery (at-least-once after a rebalance) and is dropped. Gaps are normal:
a bid that loses the compare-and-set burns its sequence number (``services/bid/app/domain/
conflict.py``), so they are counted, never treated as errors.

Each window keeps the last ``max_events`` bids of one auction for the scorers (Plan 5). Memory
is bounded twice: by ``max_events`` per auction, and by :meth:`AuctionWindows.expire`, which
drops an auction once its close time (``auction_closes_at`` on the event) plus a grace has
passed. Alerts are only useful before close (AC-14), so nothing is lost.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class Outcome(Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class SlidingWindow:
    auction_id: str
    max_events: int
    events: deque[dict[str, Any]] = field(default_factory=deque)
    last_seq: int = 0
    seen: int = 0
    gaps: int = 0
    closes_at: datetime | None = None

    def add(self, event: dict[str, Any]) -> Outcome:
        seq = int(event["server_seq"])
        if seq <= self.last_seq:
            return Outcome.DUPLICATE
        if self.last_seq and seq != self.last_seq + 1:
            self.gaps += 1
        self.last_seq = seq
        self.seen += 1
        self.events.append(event)
        while len(self.events) > self.max_events:
            self.events.popleft()
        if event.get("auction_closes_at"):
            # Anti-snipe extensions move the close later; take the latest one reported.
            closes_at = _time(event["auction_closes_at"])
            self.closes_at = max(self.closes_at, closes_at) if self.closes_at else closes_at
        return Outcome.ACCEPTED

    def sequence(self) -> list[int]:
        return [int(e["server_seq"]) for e in self.events]


class AuctionWindows:
    def __init__(self, max_events: int = 200, close_grace: timedelta = timedelta(minutes=10)
                 ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self.max_events = max_events
        self.close_grace = close_grace
        self._windows: dict[str, SlidingWindow] = {}

    def add(self, event: dict[str, Any]) -> tuple[Outcome, SlidingWindow]:
        auction_id = event["auction_id"]
        window = self._windows.get(auction_id)
        if window is None:
            window = self._windows[auction_id] = SlidingWindow(auction_id, self.max_events)
        return window.add(event), window

    def get(self, auction_id: str) -> SlidingWindow | None:
        return self._windows.get(auction_id)

    def __len__(self) -> int:
        return len(self._windows)

    def expire(self, now: datetime) -> list[str]:
        """Drop windows of auctions closed more than ``close_grace`` ago; returns their ids."""
        expired = [a for a, w in self._windows.items()
                   if w.closes_at is not None and w.closes_at + self.close_grace < now]
        for auction_id in expired:
            del self._windows[auction_id]
        return expired
