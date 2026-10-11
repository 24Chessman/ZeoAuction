"""Auction record and draft creation (docs/state-machines.md, section 1).

Pure logic, no I/O. The lifecycle transitions and their guards live in
:mod:`app.domain.lifecycle`; the anti-snipe rule in :mod:`app.domain.anti_snipe`.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

STATES = ("DRAFT", "SCHEDULED", "OPEN", "EXTENDED", "CLOSING", "CLOSED", "SETTLED", "CANCELLED")

# CT-1: bid_permitted is true exactly in these states.
BID_PERMITTED_STATES = frozenset({"OPEN", "EXTENDED"})
TERMINAL_STATES = frozenset({"SETTLED", "CANCELLED"})


@dataclass(frozen=True)
class AntiSnipePolicy:
    guard_interval_seconds: int = 120
    extension_seconds: int = 120
    max_extensions: int = 10


# Values from config/settlement-policy.yaml (ADR-0011); copied onto the row at creation.
# tests/test_anti_snipe.py keeps the two identical.
DEFAULT_POLICY = AntiSnipePolicy()


@dataclass(frozen=True)
class Auction:
    id: UUID
    seller_id: UUID
    title: str
    description: str
    category: str
    starting_price: Decimal
    reserve_price: Decimal | None
    currency: str
    state: str
    opens_at: datetime | None
    closes_at: datetime | None
    guard_interval_seconds: int
    extension_seconds: int
    max_extensions: int
    extension_count: int
    created_at: datetime
    updated_at: datetime
    version: int = 1
    original_closes_at: datetime | None = None
    winning_bid_id: UUID | None = None
    # Highest server_seq applied from bid.events, and that bid (the current leader).
    last_bid_seq: int = 0
    leading_bid_id: UUID | None = None
    # When A5 close happened; A6 drained waits a grace period after it.
    closing_since: datetime | None = None
    # The leader's bidder and amount (BidAccepted v1), frozen at A6: the winner Payment invoices.
    leading_bidder_id: UUID | None = None
    leading_amount: Decimal | None = None
    # Set once Payment has opened the order for the winning bid (saga S1, CT-4).
    settlement_order_id: UUID | None = None

    @property
    def bid_permitted(self) -> bool:
        return self.state in BID_PERMITTED_STATES

    @property
    def has_bids(self) -> bool:
        return self.last_bid_seq > 0

    @property
    def awaiting_settlement(self) -> bool:
        """CLOSED with a winner, and Payment has not opened the order yet."""
        return (self.state == "CLOSED" and self.winning_bid_id is not None
                and self.settlement_order_id is None)


class AuctionValidationError(ValueError):
    pass


def new_draft(
    *,
    auction_id: UUID,
    seller_id: UUID,
    title: str,
    description: str,
    category: str,
    starting_price: Decimal,
    reserve_price: Decimal | None,
    currency: str,
    opens_at: datetime | None,
    closes_at: datetime | None,
    now: datetime,
    policy: AntiSnipePolicy = DEFAULT_POLICY,
) -> Auction:
    """Build a DRAFT auction, enforcing the same checks as the table's CHECK constraints."""
    title = title.strip()
    if not 3 <= len(title) <= 200:
        raise AuctionValidationError("title must be 3 to 200 characters")
    if not category.strip():
        raise AuctionValidationError("category is required")
    if starting_price < 0:
        raise AuctionValidationError("starting_price must not be negative")
    if reserve_price is not None and reserve_price < starting_price:
        raise AuctionValidationError("reserve_price must not be below starting_price")
    if opens_at and closes_at and closes_at <= opens_at:
        raise AuctionValidationError("closes_at must be after opens_at")
    return Auction(
        id=auction_id,
        seller_id=seller_id,
        title=title,
        description=description,
        category=category.strip(),
        starting_price=starting_price,
        reserve_price=reserve_price,
        currency=currency,
        state="DRAFT",
        opens_at=opens_at,
        closes_at=closes_at,
        guard_interval_seconds=policy.guard_interval_seconds,
        extension_seconds=policy.extension_seconds,
        max_extensions=policy.max_extensions,
        extension_count=0,
        created_at=now,
        updated_at=now,
    )
