"""Search & Analytics API routes (Plan 6, #46, #47, #75)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.domain.models import SearchQuery, SortOption
from app.service import SearchService
from zeo_common.auth import CurrentPrincipal
from zeo_common.errors import ApiError

router = APIRouter(tags=["search"])


def get_service(request: Request) -> SearchService:
    return request.app.state.search_service


Service = Annotated[SearchService, Depends(get_service)]


# ---------------------------------------------------------------------- Schemas


class AuctionCardView(BaseModel):
    auction_id: UUID
    seller_id: UUID
    title: str
    category: str
    current_price: Decimal
    currency: str
    state: str
    closes_at: datetime | None
    opens_at: datetime | None
    flat_fee_notice: str = "Flat fee applies on win"  # SDD Fig. 8.2


class SearchResultView(BaseModel):
    items: list[AuctionCardView]
    total: int
    page: int
    page_size: int


class SellerDashboardItemView(BaseModel):
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
    simulation_notice: str = "Escrow amounts are simulated and do not involve real money"  # SDD Fig. 8.5


# ---------------------------------------------------------------------- Routes


@router.get("/api/v1/search/auctions", response_model=SearchResultView)
async def search_auctions(
    service: Service,
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    price_min: Decimal | None = Query(default=None),
    price_max: Decimal | None = Query(default=None),
    status: str | None = Query(default=None),
    sort: str = Query(default="ending_soonest"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SearchResultView:
    try:
        sort_option = SortOption(sort)
    except ValueError:
        raise ApiError(
            "VALIDATION_ERROR",
            f"Invalid sort option '{sort}'. Must be one of: {[s.value for s in SortOption]}",
            422,
        )

    query = SearchQuery(
        q=q,
        category=category,
        price_min=price_min,
        price_max=price_max,
        status=status,
        sort=sort_option,
        page=page,
        page_size=page_size,
    )
    result = await service.search(query)
    return SearchResultView(
        items=[
            AuctionCardView(
                auction_id=a.auction_id,
                seller_id=a.seller_id,
                title=a.title,
                category=a.category,
                current_price=a.current_price,
                currency=a.currency,
                state=a.state,
                closes_at=a.closes_at,
                opens_at=a.opens_at,
            )
            for a in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/api/v1/internal/auctions/{auction_id}/index",
    status_code=200,
)
async def upsert_auction_index(
    auction_id: UUID,
    body: dict,
    service: Service,
    x_internal_token: Annotated[str | None, Header()] = None,
    request: Request = None,  # type: ignore[assignment]
) -> dict:
    settings = getattr(request.app.state, "settings", None)
    expected_token = getattr(settings, "internal_service_token", "dev-token") if settings else "dev-token"
    if x_internal_token != expected_token:
        raise ApiError("FORBIDDEN", "Invalid or missing internal service token", 403)

    body["auction_id"] = str(auction_id)
    auction = await service.upsert_auction(body)
    return {"auction_id": str(auction.auction_id), "status": "indexed"}


@router.delete(
    "/api/v1/internal/auctions/{auction_id}/index",
    status_code=200,
)
async def delete_auction_index(
    auction_id: UUID,
    service: Service,
    x_internal_token: Annotated[str | None, Header()] = None,
    request: Request = None,  # type: ignore[assignment]
) -> dict:
    settings = getattr(request.app.state, "settings", None)
    expected_token = getattr(settings, "internal_service_token", "dev-token") if settings else "dev-token"
    if x_internal_token != expected_token:
        raise ApiError("FORBIDDEN", "Invalid or missing internal service token", 403)

    await service.delete_auction(auction_id)
    return {"auction_id": str(auction_id), "status": "removed"}


@router.get(
    "/api/v1/seller/{seller_id}/dashboard",
    response_model=list[SellerDashboardItemView],
)
async def get_seller_dashboard(
    seller_id: UUID,
    principal: CurrentPrincipal,
    service: Service,
) -> list[SellerDashboardItemView]:
    # Must be the seller themselves or an admin
    if not principal.is_admin and principal.user_id != seller_id:
        raise ApiError("FORBIDDEN", "You do not have access to this seller's dashboard", 403)

    items = await service.get_seller_dashboard(seller_id)
    return [
        SellerDashboardItemView(
            auction_id=item.auction_id,
            title=item.title,
            category=item.category,
            state=item.state,
            winning_bid_amount=item.winning_bid_amount,
            currency=item.currency,
            order_id=item.order_id,
            escrow_state=item.escrow_state,
            shipped_at=item.shipped_at,
            expected_payout_date=item.expected_payout_date,
            payout_amount=item.payout_amount,
        )
        for item in items
    ]
