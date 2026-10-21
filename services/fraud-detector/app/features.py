"""Shill-signal features over a sliding window of ``BidAccepted`` events (#53, pulled forward
into Plan 3, completed in Plan 5; SDD 5.4.2, Table 5.3).

Pure and incremental: :meth:`FeatureExtractor.observe` takes one event (per auction, in
``server_seq`` order, as ``bid.events`` delivers them) and returns the features of that
event's bidder in that auction, so the detector can score while the auction is live and raise
alerts before it closes (AC-14). Memory is bounded per auction: per (auction, bidder) only the
last ``window_bids`` timestamps are kept, and :meth:`forget_auction` drops a closed auction.

One feature per labelled signal in ``dataset/patterns.py``:

* ``seller_link_ratio`` (seller_linked): share of the bidder's bids, over every auction seen,
  that were on this seller's auctions;
* ``fingerprint_sharers`` / ``fingerprint_overlap`` (shared_fingerprint): other bidders seen
  on the same device, anywhere / in this auction (``app/signals/fingerprint.py``, #54);
* ``bids_per_minute`` (high_velocity): the bidder's rate in this auction over the window;
* ``interarrival_cv`` / ``interarrival_stdev`` (regular_interarrival): regularity of the
  bidder's gaps in this auction; low means machine-regular.

And the three SDD signals the dataset doesn't label, measured but not yet weighted (v1):

* ``account_age_days``: days since the account was **first seen on bid.events**. The event
  carries no sign-up date, so this is a proxy until auth exposes the real one (Plan 6);
* ``win_rate_with_seller``: of this seller's closed auctions the bidder bid in, the share it
  won (``None`` until one has closed). An auction counts as closed once an event later than its
  ``auction_closes_at`` arrives, or when it is forgotten; its leader then is the winner;
* ``sellers_bid_with``: the bidder's degree in the bidder-seller graph (FR-FRAUD-6).

Plus context the scorer weighs them against: ``bids_in_auction`` and ``share_of_auction``.
Timestamps measure durations only; ordering always comes from ``server_seq``.
"""

import heapq
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.signals.fingerprint import FingerprintIndex


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
    fingerprint_overlap: int = 0
    interarrival_stdev: float | None = None  # seconds
    account_age_days: float = 0.0
    win_rate_with_seller: float | None = None
    sellers_bid_with: int = 1
    observed_at: datetime | None = None  # the bid's accepted_at
    auction_closes_at: datetime | None = None


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class _Auction:
    seller_id: str
    closes_at: datetime | None = None
    leader: str | None = None
    settled: bool = False


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
        # bidder -> seller -> bids (across auctions)
        self._by_seller: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.fingerprints = FingerprintIndex()
        self._first_seen: dict[str, datetime] = {}
        # Auction outcomes, for win rate: open auctions, a heap of their closes, and per
        # (bidder, seller) the closed auctions taken part in and won.
        self._auctions: dict[str, _Auction] = {}
        self._participants: dict[str, set[str]] = defaultdict(set)
        self._closing: list[tuple[datetime, str]] = []
        self._closed_with: dict[tuple[str, str], int] = defaultdict(int)
        self._won_with: dict[tuple[str, str], int] = defaultdict(int)

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
        at = _time(event["accepted_at"])
        self._settle_closed(at)
        key = (auction, bidder)
        recent = self._recent.setdefault(key, deque(maxlen=self.window_bids))
        recent.append(at)
        self._in_auction[key] += 1
        self._auction_total[auction] += 1
        self._by_seller[bidder][seller] += 1
        self._first_seen.setdefault(bidder, at)
        self.fingerprints.observe(auction, bidder, event.get("device_fingerprint"))
        state = self._track(auction, seller, event.get("auction_closes_at"))
        state.leader = bidder
        self._participants[auction].add(bidder)
        return self._features(auction, bidder, seller, seq, at, state.closes_at)

    def _track(self, auction: str, seller: str, closes_at: str | None) -> _Auction:
        state = self._auctions.get(auction)
        if state is None:
            state = self._auctions[auction] = _Auction(seller)
        if closes_at:
            # Anti-snipe extensions move the close later; take the latest one reported.
            moment = _time(closes_at)
            if state.closes_at is None or moment > state.closes_at:
                state.closes_at = moment
                heapq.heappush(self._closing, (moment, auction))
        return state

    def _settle_closed(self, now: datetime) -> None:
        while self._closing and self._closing[0][0] < now:
            closes_at, auction = heapq.heappop(self._closing)
            state = self._auctions.get(auction)
            if state is not None and state.closes_at == closes_at:
                self._settle(auction)

    def _settle(self, auction: str) -> None:
        state = self._auctions.get(auction)
        if state is None or state.settled:
            return
        state.settled = True
        for bidder in self._participants.pop(auction, set()):
            self._closed_with[(bidder, state.seller_id)] += 1
            if bidder == state.leader:
                self._won_with[(bidder, state.seller_id)] += 1

    def _features(self, auction: str, bidder: str, seller: str, seq: int, at: datetime,
                  closes_at: datetime | None) -> BidderFeatures:
        key = (auction, bidder)
        recent = self._recent[key]
        by_seller = self._by_seller[bidder]
        closed = self._closed_with.get((bidder, seller), 0)
        return BidderFeatures(
            auction_id=auction,
            bidder_id=bidder,
            seller_id=seller,
            server_seq=seq,
            bids_in_auction=self._in_auction[key],
            share_of_auction=self._in_auction[key] / self._auction_total[auction],
            seller_link_ratio=by_seller[seller] / sum(by_seller.values()),
            fingerprint_sharers=self.fingerprints.sharers(bidder),
            bids_per_minute=bids_per_minute(recent),
            interarrival_cv=interarrival_cv(recent),
            fingerprint_overlap=self.fingerprints.overlap_in_auction(auction, bidder),
            interarrival_stdev=interarrival_stdev(recent),
            account_age_days=(at - self._first_seen[bidder]).total_seconds() / 86400,
            win_rate_with_seller=(self._won_with.get((bidder, seller), 0) / closed
                                  if closed else None),
            sellers_bid_with=len(by_seller),
            observed_at=at,
            auction_closes_at=closes_at,
        )

    def forget_auction(self, auction_id: str) -> None:
        """Drop a closed auction's windows (settling its outcome first). Cross-auction history
        (seller links, fingerprints, win rates) is kept: rings work several of their seller's
        auctions."""
        self._settle(auction_id)
        for key in [k for k in self._recent if k[0] == auction_id]:
            del self._recent[key]
            del self._in_auction[key]
        self._auction_total.pop(auction_id, None)
        self._last_seq.pop(auction_id, None)
        self._auctions.pop(auction_id, None)
        self._participants.pop(auction_id, None)
        self.fingerprints.forget_auction(auction_id)


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


def interarrival_stdev(times: deque[datetime] | list[datetime]) -> float | None:
    gaps = gaps_seconds(times)
    if len(gaps) < 2:
        return None
    return statistics.pstdev(gaps)
