"""Bid validation, FR-BID-2 (#19). Pure functions over already-fetched facts; no I/O.

The service gathers the facts (caller claims, CT-1 snapshot, current leader, CT-3 quote,
available funds) and calls :func:`validate_bid` **before any state change**: no
``server_seq`` is allocated and nothing is written for a rejected bid.

Order of the checks, so a bid failing several rules always gets the same code:
eligibility (suspended, then self-bidding) -> auction open -> increment -> funds.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.errors import BidRejected
from zeo_common import format_money


@dataclass(frozen=True)
class BidFacts:
    bidder_id: UUID
    bidder_suspended: bool
    seller_id: UUID
    auction_state: str
    bid_permitted: bool
    amount: Decimal
    min_next_bid: Decimal
    available_funds: Decimal


def minimum_next_bid(
    leader_amount: Decimal | None, starting_price: Decimal, min_increment: Decimal
) -> Decimal:
    """The first bid may equal the starting price; every later bid must beat the leader by
    the increment."""
    if leader_amount is None:
        return starting_price
    return leader_amount + min_increment


def check_eligibility(bidder_id: UUID, suspended: bool, seller_id: UUID) -> None:
    if suspended:
        raise BidRejected("ACCOUNT_SUSPENDED", "Your account is suspended and cannot bid")
    if bidder_id == seller_id:
        raise BidRejected("SELF_BIDDING_FORBIDDEN", "Sellers cannot bid on their own auction")


def check_auction_open(state: str, bid_permitted: bool) -> None:
    if not bid_permitted:
        raise BidRejected(
            "AUCTION_NOT_OPEN", f"Auction is {state} and is not accepting bids", {"state": state}
        )


def check_increment(amount: Decimal, min_next_bid: Decimal) -> None:
    if amount < min_next_bid:
        raise BidRejected(
            "BID_BELOW_INCREMENT",
            f"Minimum next bid is {format_money(min_next_bid)}",
            {"min_next_bid": format_money(min_next_bid)},
        )


def check_funds(amount: Decimal, available: Decimal) -> None:
    if amount > available:
        raise BidRejected("INSUFFICIENT_FUNDS", "Insufficient funds for this bid")


def validate_bid(facts: BidFacts) -> None:
    """Raise :class:`BidRejected` with the taxonomy code of the first failing rule."""
    check_eligibility(facts.bidder_id, facts.bidder_suspended, facts.seller_id)
    check_auction_open(facts.auction_state, facts.bid_permitted)
    check_increment(facts.amount, facts.min_next_bid)
    check_funds(facts.amount, facts.available_funds)
