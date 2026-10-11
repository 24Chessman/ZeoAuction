"""Anti-snipe auto-extension, row A4 of docs/state-machines.md (#32, FR-AO-4).

Pure logic, no I/O. Applied to every accepted bid read from ``bid.events``, in ``server_seq``
order. A bid accepted inside the guard interval before ``closes_at`` moves OPEN/EXTENDED to
EXTENDED and pushes ``closes_at`` forward by ``extension_seconds``, at most ``max_extensions``
times. Past the cap the bid still stands; the auction simply is not extended (not an error).

A redelivered event (``server_seq`` not above the last one applied) changes nothing, so
at-least-once delivery from Kafka can never extend an auction twice for one bid.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.domain.auction import Auction
from app.domain.lifecycle import SYSTEM, transition


@dataclass(frozen=True)
class AcceptedBid:
    """The fields of ``BidAccepted v1`` the orchestrator uses."""

    auction_id: UUID
    bid_id: UUID
    server_seq: int
    accepted_at: datetime
    # Who bid and how much; the winner's become the settlement order (#33).
    bidder_id: UUID | None = None
    amount: Decimal | None = None


@dataclass(frozen=True)
class BidOutcome:
    auction: Auction
    extended: bool
    duplicate: bool = False


def in_guard_interval(auction: Auction, accepted_at: datetime) -> bool:
    if auction.closes_at is None:
        return False
    return accepted_at > auction.closes_at - timedelta(seconds=auction.guard_interval_seconds)


def should_extend(auction: Auction, accepted_at: datetime) -> bool:
    return (
        auction.bid_permitted
        and auction.extension_count < auction.max_extensions
        and in_guard_interval(auction, accepted_at)
    )


def apply_bid(auction: Auction, bid: AcceptedBid, now: datetime) -> BidOutcome:
    """Record the bid as the leader and extend if the rule says so."""
    if bid.server_seq <= auction.last_bid_seq:
        return BidOutcome(auction, extended=False, duplicate=True)
    leader = {"last_bid_seq": bid.server_seq, "leading_bid_id": bid.bid_id,
              "leading_bidder_id": bid.bidder_id, "leading_amount": bid.amount}
    if should_extend(auction, bid.accepted_at):
        extended = transition(auction, "extend", now=now, actor=SYSTEM)
        return BidOutcome(replace(extended, **leader), extended=True)
    recorded = replace(auction, updated_at=now, version=auction.version + 1, **leader)
    return BidOutcome(recorded, extended=False)
