"""Auction Orchestration routes (SDD 7.2).

Listing is behind the KYC listing gate (CT-2, #41): ``POST /auctions`` and ``publish`` take
the seller from the verified token and refuse anyone whose ``kyc_status`` claim is not
VERIFIED with ``SELLER_NOT_VERIFIED``, or who is suspended with ``ACCOUNT_SUSPENDED``. The gate
also refuses tokens minted before a KYC status change (``TOKEN_STALE``), so an approval or a
suspension applies at once. No request calls the KYC service (ADR-0005).

``POST /auctions/{id}/events`` is the administrators' operator override (for example, opening
an auction early in a demo). The platform's own timer and the anti-snipe consumer drive the
lifecycle otherwise.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.domain.auction import Auction
from app.service import AuctionService, Draft
from zeo_common import format_money, parse_money
from zeo_common.auth import AdminPrincipal, CurrentPrincipal
from zeo_common.gateway import VerifiedSeller
from zeo_common.money import MONEY_PATTERN

router = APIRouter(prefix="/api/v1", tags=["auctions"])

MoneyStr = Annotated[str, Field(pattern=MONEY_PATTERN, examples=["100.00"])]
OperatorEvent = Literal["open", "close", "drained", "settle"]


def get_service(request: Request) -> AuctionService:
    return request.app.state.auction_service


Service = Annotated[AuctionService, Depends(get_service)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class CreateAuctionRequest(BaseModel):
    # The seller is the caller; a seller_id in the body is refused, not ignored.
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    category: str
    starting_price: MoneyStr
    reserve_price: MoneyStr | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class TransitionRequest(BaseModel):
    event: OperatorEvent


class AuctionView(BaseModel):
    auction_id: UUID
    seller_id: UUID
    title: str
    description: str
    category: str
    starting_price: str
    reserve_price: str | None
    currency: str
    state: str
    opens_at: datetime | None
    closes_at: datetime | None
    original_closes_at: datetime | None
    extension_count: int
    max_extensions: int
    guard_interval_seconds: int
    extension_seconds: int
    winning_bid_id: UUID | None
    version: int


class AuctionStateView(BaseModel):
    """CT-1 ``AuctionState``; the shape is pinned by the contract test."""

    auction_id: UUID
    seller_id: UUID
    state: str
    bid_permitted: bool
    currency: str
    starting_price: str
    closes_at: datetime | None
    as_of: datetime


def to_view(auction: Auction) -> AuctionView:
    return AuctionView(
        auction_id=auction.id,
        seller_id=auction.seller_id,
        title=auction.title,
        description=auction.description,
        category=auction.category,
        starting_price=format_money(auction.starting_price),
        reserve_price=(
            None if auction.reserve_price is None else format_money(auction.reserve_price)
        ),
        currency=auction.currency,
        state=auction.state,
        opens_at=auction.opens_at,
        closes_at=auction.closes_at,
        original_closes_at=auction.original_closes_at,
        extension_count=auction.extension_count,
        max_extensions=auction.max_extensions,
        guard_interval_seconds=auction.guard_interval_seconds,
        extension_seconds=auction.extension_seconds,
        winning_bid_id=auction.winning_bid_id,
        version=auction.version,
    )


@router.post("/auctions", status_code=201, response_model=AuctionView)
async def create_auction(
    body: CreateAuctionRequest, seller: VerifiedSeller, service: Service
) -> AuctionView:
    draft = Draft(
        title=body.title,
        description=body.description,
        category=body.category,
        starting_price=parse_money(body.starting_price),
        reserve_price=None if body.reserve_price is None else parse_money(body.reserve_price),
        currency=body.currency,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
    )
    return to_view(await service.create(seller, draft))


@router.get("/auctions/{auction_id}", response_model=AuctionView)
async def get_auction(auction_id: UUID, service: Service) -> AuctionView:
    return to_view(await service.load(auction_id))


@router.post("/auctions/{auction_id}/publish", response_model=AuctionView)
async def publish_auction(
    auction_id: UUID, seller: VerifiedSeller, service: Service
) -> AuctionView:
    """A1: DRAFT -> SCHEDULED. Seller only, through the listing gate."""
    return to_view(await service.apply(seller, auction_id, "publish"))


@router.post("/auctions/{auction_id}/cancel", response_model=AuctionView)
async def cancel_auction(
    auction_id: UUID, principal: CurrentPrincipal, service: Service
) -> AuctionView:
    """A8: DRAFT or SCHEDULED -> CANCELLED. The seller or an administrator, before any bid."""
    return to_view(await service.apply(principal, auction_id, "cancel"))


@router.post("/auctions/{auction_id}/events", response_model=AuctionView)
async def apply_auction_event(
    auction_id: UUID, body: TransitionRequest, admin: AdminPrincipal, service: Service
) -> AuctionView:
    """Operator override of a timer or settlement event; the table still applies."""
    return to_view(await service.apply(admin, auction_id, body.event))


@router.get("/auctions/{auction_id}/state", response_model=AuctionStateView)
async def get_auction_state(auction_id: UUID, service: Service) -> AuctionStateView:
    """CT-1 provider. Internal: not routed through the public gateway."""
    auction = await service.load(auction_id)
    return AuctionStateView(
        auction_id=auction.id,
        seller_id=auction.seller_id,
        state=auction.state,
        bid_permitted=auction.bid_permitted,
        currency=auction.currency,
        starting_price=format_money(auction.starting_price),
        closes_at=auction.closes_at,
        as_of=utc_now(),
    )
