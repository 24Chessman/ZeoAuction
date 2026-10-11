"""Deterministic server-side conflict resolution, FR-BID-3 / ADR-0001 (#20).

Each attempt: check the amount against the leader we read -> allocate ``server_seq`` ->
compare-and-set ``price:{auction_id}`` expecting that same leader. Exactly one of any set of
racing bids wins a given compare-and-set. A loser re-reads the new leader and is
re-validated against the new price: it is either accepted at a fresh, higher ``server_seq``
or rejected with ``BID_BELOW_INCREMENT``.

Why this makes the outcome replayable: a bid is accepted only if the leader it was checked
against is still the leader, and its ``server_seq`` is higher than that leader's. So the
accepted bids, ordered by ``server_seq``, are exactly the sequence that :func:`replay`
re-derives from the log: each one beats its predecessor by the increment. Replaying
``bid.events`` therefore always produces the same winner (AC-04). Simultaneous equal bids
resolve the same way: the first to win the compare-and-set is the leader and every other
equal bid fails the increment check on re-validation.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.model import Leader
from app.domain.sequencing import SequenceAllocator
from app.domain.validation import check_increment, minimum_next_bid
from app.errors import BidRejected


class PriceStore(Protocol):
    async def leader(self, auction_id: UUID) -> Leader | None: ...

    async def compare_and_set(self, auction_id: UUID, expected_seq: int, new: Leader) -> bool: ...


@dataclass(frozen=True)
class Threshold:
    """What a bid must reach against one particular leader."""

    min_next_bid: Decimal
    increment_stale: bool = False


ThresholdFn = Callable[[Leader | None], Awaitable[Threshold]]


@dataclass(frozen=True)
class Resolution:
    accepted: Leader
    previous: Leader | None
    increment_stale: bool
    attempts: int


class ContentionExceeded(Exception):
    """The leader kept changing for ``max_attempts`` rounds; the bid was not accepted."""


class ConflictResolver:
    def __init__(
        self,
        store: PriceStore,
        sequencer: SequenceAllocator,
        *,
        max_attempts: int = 5,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.sequencer = sequencer
        self.max_attempts = max_attempts
        self.clock = clock

    async def resolve(
        self,
        *,
        auction_id: UUID,
        bid_id: UUID,
        bidder_id: UUID,
        amount: Decimal,
        closes_at: datetime | None,
        threshold_for: ThresholdFn,
        leader: Leader | None,
        threshold: Threshold | None = None,
    ) -> Resolution:
        """Sequence and apply one bid. ``leader``/``threshold`` are what validation used."""
        current = threshold
        for attempt in range(1, self.max_attempts + 1):
            if current is None:
                current = await threshold_for(leader)
            check_increment(amount, current.min_next_bid)
            if closes_at is not None and self.clock() >= closes_at:
                raise BidRejected("AUCTION_CLOSED", "The auction closed before the bid was placed")
            seq = await self.sequencer.allocate(auction_id)
            candidate = Leader(amount=amount, server_seq=seq, bid_id=bid_id, bidder_id=bidder_id)
            expected = leader.server_seq if leader else 0
            if await self.store.compare_and_set(auction_id, expected, candidate):
                return Resolution(candidate, leader, current.increment_stale, attempt)
            leader = await self.store.leader(auction_id)  # lost: re-validate against it
            current = None
        raise ContentionExceeded(str(auction_id))


def replay(
    bids: Iterable[Leader],
    starting_price: Decimal,
    increment_for: Callable[[Decimal], Decimal],
) -> Leader | None:
    """Re-derive the winner from a bid log, in ``server_seq`` order, ignoring arrival order.

    A bid counts if it meets the minimum against the leader so far. Applied to the accepted
    bids on ``bid.events`` it returns the live leader; applied to any shuffle of the same log
    it returns the same leader.
    """
    winner: Leader | None = None
    for bid in sorted(bids, key=lambda b: b.server_seq):
        floor = minimum_next_bid(
            winner.amount if winner else None,
            starting_price,
            increment_for(winner.amount) if winner else Decimal("0"),
        )
        if bid.amount >= floor:
            winner = bid
    return winner
