"""Value types shared by the bid domain and its Redis adapter."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Leader:
    """The current highest accepted bid of one auction (``price:{auction_id}``)."""

    amount: Decimal
    server_seq: int
    bid_id: UUID
    bidder_id: UUID
