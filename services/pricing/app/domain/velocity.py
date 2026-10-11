"""Rolling bid velocity per auction, fed by ``bid.events`` (#42, FR-PRICE-1).

Each auction keeps fixed-width buckets (default 5 s) covering the rolling window (default 60 s);
the rate is the count inside the window scaled to bids per minute. Buckets are also the unit
persisted to ``pricing.velocity_windows``, so a restart can warm the tracker back up
(:meth:`VelocityTracker.restore`).

Delivery is at-least-once, so an event whose ``server_seq`` is not above the last one seen for
its auction is ignored. ``accepted_at`` only places a bid in a bucket (a duration); ordering
always comes from ``server_seq``. Memory is bounded: buckets older than the window are pruned
on every touch, and :meth:`VelocityTracker.forget_idle` drops auctions with nothing left.
"""

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class Bucket:
    start: datetime
    count: int


def _floor(moment: datetime, seconds: int) -> datetime:
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)


class VelocityTracker:
    def __init__(self, window_seconds: int = 60, bucket_seconds: int = 5) -> None:
        if bucket_seconds <= 0 or window_seconds < bucket_seconds:
            raise ValueError("need 0 < bucket_seconds <= window_seconds")
        if window_seconds % bucket_seconds:
            raise ValueError("window_seconds must be a whole number of buckets")
        self.window_seconds = window_seconds
        self.bucket_seconds = bucket_seconds
        self._buckets: dict[str, deque[Bucket]] = {}
        self._last_seq: dict[str, int] = {}

    def record(self, auction_id: str, server_seq: int, accepted_at: datetime) -> Bucket | None:
        """Count one accepted bid. Returns the bucket it landed in, or ``None`` for a replay
        of a ``server_seq`` already counted."""
        if server_seq <= self._last_seq.get(auction_id, 0):
            return None
        self._last_seq[auction_id] = server_seq
        start = _floor(accepted_at, self.bucket_seconds)
        buckets = self._buckets.setdefault(auction_id, deque())
        for bucket in reversed(buckets):
            if bucket.start == start:
                bucket.count += 1
                return bucket
            if bucket.start < start:
                break
        bucket = Bucket(start, 1)
        buckets.append(bucket)
        if len(buckets) > 1 and buckets[-2].start > start:  # late arrival: keep time order
            ordered = sorted(buckets, key=lambda b: b.start)
            buckets.clear()
            buckets.extend(ordered)
        return bucket

    def restore(self, auction_id: str, start: datetime, count: int) -> None:
        """Re-load one persisted bucket after a restart (replaces any in-memory count)."""
        buckets = self._buckets.setdefault(auction_id, deque())
        for bucket in buckets:
            if bucket.start == start:
                bucket.count = max(bucket.count, count)
                return
        buckets.append(Bucket(start, count))
        ordered = sorted(buckets, key=lambda b: b.start)
        buckets.clear()
        buckets.extend(ordered)

    def bids_per_minute(self, auction_id: str, now: datetime) -> float:
        buckets = self._buckets.get(auction_id)
        if not buckets:
            return 0.0
        self._prune(buckets, now)
        horizon = now - timedelta(seconds=self.window_seconds)
        count = sum(b.count for b in buckets if horizon < b.start + timedelta(
            seconds=self.bucket_seconds) and b.start <= now)
        return count * 60.0 / self.window_seconds

    def bucket_count(self, auction_id: str, start: datetime) -> int | None:
        for bucket in self._buckets.get(auction_id, ()):
            if bucket.start == start:
                return bucket.count
        return None

    def auctions(self) -> list[str]:
        return list(self._buckets)

    def forget_idle(self, now: datetime) -> list[str]:
        """Drop auctions with no bid inside the window; returns their ids."""
        idle = []
        for auction_id, buckets in list(self._buckets.items()):
            self._prune(buckets, now)
            if not buckets:
                idle.append(auction_id)
                del self._buckets[auction_id]
                # A replay of an idle auction's old bid lands outside the window anyway.
                self._last_seq.pop(auction_id, None)
        return idle

    def _prune(self, buckets: deque[Bucket], now: datetime) -> None:
        horizon = now - timedelta(seconds=self.window_seconds)
        while buckets and buckets[0].start + timedelta(seconds=self.bucket_seconds) <= horizon:
            buckets.popleft()
