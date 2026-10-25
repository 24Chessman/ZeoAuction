"""Search & Analytics use cases (Plan 6, #46, #47, #75)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.adapters.order_client import OrderClient
from app.adapters.search_repo import SearchRepository
from app.domain.models import (
    IndexedAuction,
    SearchQuery,
    SearchResult,
    SellerDashboardItem,
    SortOption,
)


class SearchService:
    def __init__(
        self,
        repo: SearchRepository,
        order_client: OrderClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.order_client = order_client
        self.clock = clock

    async def search(self, query: SearchQuery) -> SearchResult:
        return await self.repo.search(query)

    async def upsert_auction(self, data: dict) -> IndexedAuction:
        auction = IndexedAuction(
            auction_id=UUID(str(data["auction_id"])),
            seller_id=UUID(str(data["seller_id"])),
            title=str(data["title"]),
            description=str(data.get("description", "")),
            category=str(data["category"]),
            current_price=Decimal(str(data["current_price"])),
            currency=str(data["currency"]),
            state=str(data["state"]),
            opens_at=_parse_dt(data.get("opens_at")),
            closes_at=_parse_dt(data.get("closes_at")),
            created_at=_parse_dt(data.get("created_at")) or self.clock(),
            updated_at=_parse_dt(data.get("updated_at")) or self.clock(),
        )
        return await self.repo.upsert(auction)

    async def delete_auction(self, auction_id: UUID) -> None:
        await self.repo.delete(auction_id)

    async def get_seller_dashboard(self, seller_id: UUID) -> list[SellerDashboardItem]:
        listings = await self.repo.get_seller_listings(seller_id)
        orders = await self.order_client.get_seller_orders(seller_id)

        # Build a lookup: auction_id -> order
        order_by_auction = {o.auction_id: o for o in orders}

        result: list[SellerDashboardItem] = []
        for listing in listings:
            order = order_by_auction.get(listing.auction_id)
            if order:
                expected_payout_date = None
                if order.shipped_at is not None:
                    expected_payout_date = order.shipped_at + timedelta(
                        days=order.protection_window_days
                    )
                payout_amount: Decimal | None = order.captured_amount - order.fee_amount
                result.append(
                    SellerDashboardItem(
                        auction_id=listing.auction_id,
                        title=listing.title,
                        category=listing.category,
                        state=listing.state,
                        winning_bid_amount=order.captured_amount,
                        currency=listing.currency,
                        order_id=order.order_id,
                        escrow_state=order.state,
                        shipped_at=order.shipped_at,
                        expected_payout_date=expected_payout_date,
                        payout_amount=payout_amount,
                    )
                )
            else:
                result.append(
                    SellerDashboardItem(
                        auction_id=listing.auction_id,
                        title=listing.title,
                        category=listing.category,
                        state=listing.state,
                        winning_bid_amount=None,
                        currency=listing.currency,
                    )
                )
        return result


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None
