"""Settlement hand-off, A6 -> A7 of docs/state-machines.md (#33).

Pure logic, no I/O. Once an auction is CLOSED with a winner, Orchestration asks Payment to open
the order and invoice for the winning bid (saga S1, internal contract CT-4,
``contracts/openapi/internal/settlement.v1.yaml``). Payment captures the winner's payment into
escrow, and its ``HELD`` step on ``payment.events`` applies A7 ``settle``.

Only the winner is ever sent: losing bidders are never invoiced (AC-09). The request is keyed
``auction:{id}:settle``, so a retry after a timeout or an open breaker opens nothing twice.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.auction import Auction


class NotSettleable(ValueError):
    pass


@dataclass(frozen=True)
class SettlementRequest:
    auction_id: UUID
    buyer_id: UUID
    seller_id: UUID
    winning_bid_id: UUID
    winning_bid_amount: Decimal
    currency: str

    @property
    def idempotency_key(self) -> str:
        return f"auction:{self.auction_id}:settle"


def settlement_request(auction: Auction) -> SettlementRequest:
    if not auction.awaiting_settlement:
        raise NotSettleable(f"auction {auction.id} is not CLOSED with an unsettled winner")
    if auction.leading_bidder_id is None or auction.leading_amount is None:
        raise NotSettleable(f"auction {auction.id} has no recorded winner or amount")
    return SettlementRequest(
        auction_id=auction.id, buyer_id=auction.leading_bidder_id, seller_id=auction.seller_id,
        winning_bid_id=auction.winning_bid_id, winning_bid_amount=auction.leading_amount,
        currency=auction.currency,
    )


def record_order(auction: Auction, order_id: UUID, now: datetime) -> Auction:
    return replace(auction, settlement_order_id=order_id, updated_at=now,
                   version=auction.version + 1)
