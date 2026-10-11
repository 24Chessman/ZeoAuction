"""Shill-signal features over a sliding window of ``BidAccepted`` events (#53, pulled forward
into Plan 3; SDD 5.4).

Pure and incremental: :meth:`FeatureExtractor.observe` takes one event (per auction, in
``server_seq`` order, as ``bid.events`` delivers them) and returns the features of that
event's bidder in that auction, so the Plan 4/5 detector can score while the auction is live
and raise alerts before it closes (AC-14). Memory is bounded: per (auction, bidder) only the
last ``window_bids`` timestamps are kept, and :meth:`forget_auction` drops a closed auction.

One feature per labelled signal in ``dataset/patterns.py``:

* ``seller_link_ratio`` (seller_linked): share of the bidder's bids, over every auction seen,
  that were on this seller's auctions;
* ``fingerprint_sharers`` (shared_fingerprint): other bidders seen on the same device;
* ``bids_per_minute`` (high_velocity): the bidder's rate in this auction over the window;
* ``interarrival_cv`` (regular_interarrival): coefficient of variation of the bidder's gaps
  in this auction; low means machine-regular.

Plus context the scorer weighs them against: ``bids_in_auction`` and ``share_of_auction``.
Timestamps measure durations only; ordering always comes from ``server_seq``.
"""

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BidderFeatures:
    auction_id: str
    bidder_id: str
    seller_id: str
    server_seq: int
    bids_in_auction: int
    share_of_auction: float
    seller_link_ratio: float
    fingerprint_sharers: int
    bids_per_minute: float
    interarrival_cv: float | None  # None until there are at least three bids (two gaps)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FeatureExtractor:
    def __init__(self, window_bids: int = 10) -> None:
        if window_bids < 3:
            raise ValueError("the window needs at least three bids for an inter-arrival CV")
        self.window_bids = window_bids
        # (auction, bidder) -> recent acceptance times
        self._recent: dict[tuple[str, str], deque[datetime]] = {}
        self._in_auction: dict[tuple[str, str], int] = defaultdict(int)
        self._auction_total: dict[str, int] = defaultdict(int)
        self._last_seq: dict[str, int] = {}
        # bidder -> seller -> bids (across auctions), and device fingerprint -> bidders
        self._by_seller: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._fingerprints: dict[str, set[str]] = defaultdict(set)
        self._bidder_fingerprints: dict[str, set[str]] = defaultdict(set)

    def observe(self, event: dict[str, Any]) -> BidderFeatures | None:
        """Fold one ``BidAccepted v1`` in. Returns None for an event already seen (redelivery)
        or of an unknown ``schema_version``."""
        if event.get("schema_version") != 1:
            return None
        auction = event["auction_id"]
        bidder = event["bidder_id"]
        seller = event.get("seller_id", "")
        seq = int(event["server_seq"])
        if seq <= self._last_seq.get(auction, 0):
            return None
        self._last_seq[auction] = seq
        key = (auction, bidder)
        recent = self._recent.setdefault(key, deque(maxlen=self.window_bids))
        recent.append(_time(event["accepted_at"]))
        self._in_auction[key] += 1
        self._auction_total[auction] += 1
        self._by_seller[bidder][seller] += 1
        fingerprint = event.get("device_fingerprint")
        if fingerprint:
            self._fingerprints[fingerprint].add(bidder)
            self._bidder_fingerprints[bidder].add(fingerprint)
        return self._features(auction, bidder, seller, seq)

    def _features(self, auction: str, bidder: str, seller: str, seq: int) -> BidderFeatures:
        key = (auction, bidder)
        recent = self._recent[key]
        by_seller = self._by_seller[bidder]
        sharers = set().union(*(self._fingerprints[f] for f in self._bidder_fingerprints[bidder])) \
            if self._bidder_fingerprints[bidder] else set()
        return BidderFeatures(
            auction_id=auction,
            bidder_id=bidder,
            seller_id=seller,
            server_seq=seq,
            bids_in_auction=self._in_auction[key],
            share_of_auction=self._in_auction[key] / self._auction_total[auction],
            seller_link_ratio=by_seller[seller] / sum(by_seller.values()),
            fingerprint_sharers=len(sharers - {bidder}),
            bids_per_minute=bids_per_minute(recent),
            interarrival_cv=interarrival_cv(recent),
        )

    def forget_auction(self, auction_id: str) -> None:
        """Drop a closed auction's windows. Cross-auction history (seller links,
        fingerprints) is kept: rings work several of their seller's auctions."""
        for key in [k for k in self._recent if k[0] == auction_id]:
            del self._recent[key]
            del self._in_auction[key]
        self._auction_total.pop(auction_id, None)
        self._last_seq.pop(auction_id, None)


def gaps_seconds(times: deque[datetime] | list[datetime]) -> list[float]:
    ordered = list(times)
    return [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:], strict=False)]


def bids_per_minute(times: deque[datetime] | list[datetime]) -> float:
    if len(times) < 2:
        return 0.0
    span = (times[-1] - times[0]).total_seconds()
    # Bids that land in the same instant are as fast as it gets; cap instead of dividing by 0.
    return (len(times) - 1) / max(span / 60, 1 / 60)


def interarrival_cv(times: deque[datetime] | list[datetime]) -> float | None:
    gaps = gaps_seconds(times)
    if len(gaps) < 2:
        return None
    mean = statistics.fmean(gaps)
    if mean <= 0:
        return 0.0
    return statistics.pstdev(gaps) / mean
