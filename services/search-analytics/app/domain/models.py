"""Search and Seller Dashboard models (Plan 6, #46, #47, #75)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class SortOption(StrEnum):
    ENDING_SOONEST = "ending_soonest"
    NEWEST = "newest"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"


@dataclass(frozen=True)
class IndexedAuction:
    auction_id: UUID
    seller_id: UUID
    title: str
    description: str
    category: str
    current_price: Decimal
    currency: str
    state: str
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SearchQuery:
    q: str | None = None
    category: str | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    status: str | None = None
    sort: SortOption = SortOption.ENDING_SOONEST
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class SearchResult:
    items: list[IndexedAuction]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class SellerDashboardItem:
    auction_id: UUID
    title: str
    category: str
    state: str
    winning_bid_amount: Decimal | None
    currency: str
    order_id: UUID | None = None
    escrow_state: str | None = None
    shipped_at: datetime | None = None
    expected_payout_date: datetime | None = None
    payout_amount: Decimal | None = None
