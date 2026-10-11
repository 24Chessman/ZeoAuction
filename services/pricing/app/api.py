"""Pricing Engine routes: internal contract CT-3 (contracts/openapi/internal/pricing.v1.yaml).

Both routes are internal (Bid Processing calls the first on every validated bid) and, like
CT-1, unauthenticated inside the private network. Money is a two-decimal string both ways.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.service import PricingService
from zeo_common import format_money, parse_money
from zeo_common.money import MONEY_PATTERN

router = APIRouter(prefix="/api/v1", tags=["pricing"])


def get_service(request: Request) -> PricingService:
    return request.app.state.pricing_service


Service = Annotated[PricingService, Depends(get_service)]


class MinIncrementView(BaseModel):
    auction_id: UUID
    min_increment: str = Field(examples=["5.00"])
    min_next_bid: str = Field(examples=["1255.00"])
    hot: bool
    computed_at: datetime


class VelocityView(BaseModel):
    auction_id: UUID
    bids_per_minute: float
    hot: bool
    computed_at: datetime


@router.get("/pricing/{auction_id}/min-increment", response_model=MinIncrementView)
async def get_min_increment(
    auction_id: UUID,
    service: Service,
    current_price: Annotated[str, Query(pattern=MONEY_PATTERN, examples=["1250.00"])],
) -> MinIncrementView:
    quote = await service.quote(auction_id, parse_money(current_price))
    return MinIncrementView(
        auction_id=quote.auction_id,
        min_increment=format_money(quote.min_increment),
        min_next_bid=format_money(quote.min_next_bid),
        hot=quote.hot,
        computed_at=quote.computed_at,
    )


@router.get("/pricing/{auction_id}/velocity", response_model=VelocityView)
async def get_velocity(auction_id: UUID, service: Service) -> VelocityView:
    velocity = await service.velocity(auction_id)
    return VelocityView(
        auction_id=velocity.auction_id,
        bids_per_minute=velocity.bids_per_minute,
        hot=velocity.hot,
        computed_at=velocity.computed_at,
    )
