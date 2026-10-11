"""Bid Processing public routes (contracts/openapi/bid-service.v1.yaml, #18/#19)."""

import hashlib
import hmac
import time
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.auction_client import AuctionNotFound, AuctionStateUnavailable
from app.adapters.bid_repo import BidRepository, StoredBid
from app.service import BidService
from zeo_common import ApiError, format_money, parse_money
from zeo_common.auth import CurrentPrincipal
from zeo_common.errors import error_response
from zeo_common.money import MONEY_PATTERN

router = APIRouter(prefix="/api/v1", tags=["bids"])

REPLAY_HEADER = "Idempotent-Replay"


class PlaceBidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Annotated[str, Field(pattern=MONEY_PATTERN, examples=["1250.00"])]
    device_fingerprint: Annotated[str | None, Field(max_length=256)] = None


class BidAcceptedView(BaseModel):
    bid_id: UUID
    auction_id: UUID
    server_seq: int
    current_price: str
    min_next_bid: str
    accepted_at: datetime


class BidView(BaseModel):
    bid_id: UUID
    auction_id: UUID
    amount: str
    server_seq: int
    accepted_at: datetime
    bidder_alias: str


class BidPageView(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[BidView]


def get_service(request: Request) -> BidService:
    return request.app.state.bid_service


def get_bids(request: Request) -> BidRepository:
    return request.app.state.bid_repository


def bidder_alias(secret: str, auction_id: UUID, bidder_id: UUID) -> str:
    """Stable per-auction pseudonym: the same bidder reads the same in one auction and
    differently in another, and the bidder id is never exposed."""
    digest = hmac.new(secret.encode(), f"{auction_id}:{bidder_id}".encode(), hashlib.sha256)
    return f"bidder-{digest.hexdigest()[:8]}"


def to_view(request: Request, bid: StoredBid) -> BidView:
    return BidView(
        bid_id=bid.bid_id,
        auction_id=bid.auction_id,
        amount=format_money(bid.amount),
        server_seq=bid.server_seq,
        accepted_at=bid.accepted_at,
        bidder_alias=bidder_alias(request.app.state.alias_secret, bid.auction_id, bid.bidder_id),
    )


Service = Annotated[BidService, Depends(get_service)]
Bids = Annotated[BidRepository, Depends(get_bids)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]


@router.post(
    "/auctions/{auction_id}/bids",
    status_code=202,
    response_model=BidAcceptedView,
    operation_id="placeBid",
    responses={200: {"model": BidAcceptedView, "description": "Idempotent replay"}},
)
async def place_bid(
    request: Request,
    auction_id: UUID,
    body: PlaceBidRequest,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey,
    service: Service,
) -> Any:
    started = time.perf_counter()
    result = await service.place_bid(
        principal, auction_id, parse_money(body.amount), idempotency_key, body.device_fingerprint
    )
    headers = {REPLAY_HEADER: "true"} if result.replay else {}
    if result.status_code >= 400:
        response = error_response(
            result.status_code, result.body["code"], result.body["message"],
            result.body.get("details"),
        )
        response.headers.update(headers)
        return response
    if result.status_code == 202:
        service.metrics.ack_latency.observe(time.perf_counter() - started)
    return JSONResponse(result.body, status_code=result.status_code, headers=headers)


@router.get("/auctions/{auction_id}/bids", response_model=BidPageView, operation_id="listBids")
async def list_bids(
    request: Request,
    auction_id: UUID,
    service: Service,
    bids: Bids,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BidPageView:
    try:
        await service.auctions.get_state(auction_id)
    except AuctionNotFound as exc:
        raise ApiError("NOT_FOUND", f"Auction {auction_id} does not exist", 404) from exc
    except AuctionStateUnavailable:
        pass  # history is still readable while the orchestrator is down
    items, total = await bids.page(auction_id, page, page_size)
    return BidPageView(
        page=page, page_size=page_size, total=total, items=[to_view(request, b) for b in items]
    )


@router.get("/bids/{bid_id}", response_model=BidView, operation_id="getBid")
async def get_bid(
    request: Request, bid_id: UUID, principal: CurrentPrincipal, bids: Bids
) -> BidView:
    bid = await bids.get(bid_id)
    if bid is None or bid.bidder_id != principal.user_id:
        # Someone else's bid is indistinguishable from a missing one.
        raise ApiError("NOT_FOUND", f"Bid {bid_id} does not exist", 404)
    return to_view(request, bid)
