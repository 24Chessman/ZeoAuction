"""Admin & Moderation API routes (Plan 6, #81, #82, #83)."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.admin_repo import Broadcast
from app.domain.listing_review import ListingReview
from app.domain.suspension import UserSuspension
from app.service import AdminService
from zeo_common.auth import AdminPrincipal, CurrentPrincipal

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def get_service(request: Request) -> AdminService:
    return request.app.state.admin_service


Service = Annotated[AdminService, Depends(get_service)]


# ---------------------------------------------------------------------- Schemas


class SuspendUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: Literal[
        "SHILL_BIDDING",
        "FRAUD",
        "ABUSIVE_BEHAVIOR",
        "NON_PAYMENT",
        "TERMS_VIOLATION",
        "OTHER",
    ]
    note: str | None = None


class ReinstateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = None


class ReportListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auction_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class ReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    note: str | None = None


class BroadcastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)


class SuspensionView(BaseModel):
    id: UUID
    user_id: UUID
    reason_code: str
    note: str | None
    suspended_by: UUID
    suspended_at: datetime
    lifted_by: UUID | None
    lifted_at: datetime | None
    is_active: bool


class ListingReviewView(BaseModel):
    id: UUID
    auction_id: UUID
    source: str
    state: str
    reported_by: UUID | None
    reason: str | None
    reviewed_by: UUID | None
    decided_at: datetime | None
    created_at: datetime | None


class BroadcastView(BaseModel):
    id: UUID
    title: str
    body: str
    created_by: UUID
    created_at: datetime


def suspension_view(s: UserSuspension) -> SuspensionView:
    return SuspensionView(
        id=s.id,
        user_id=s.user_id,
        reason_code=s.reason_code.value,
        note=s.note,
        suspended_by=s.suspended_by,
        suspended_at=s.suspended_at,
        lifted_by=s.lifted_by,
        lifted_at=s.lifted_at,
        is_active=s.is_active,
    )


def review_view(r: ListingReview) -> ListingReviewView:
    return ListingReviewView(
        id=r.id,
        auction_id=r.auction_id,
        source=r.source.value,
        state=r.state.value,
        reported_by=r.reported_by,
        reason=r.reason,
        reviewed_by=r.reviewed_by,
        decided_at=r.decided_at,
        created_at=r.created_at,
    )


def broadcast_view(b: Broadcast) -> BroadcastView:
    return BroadcastView(
        id=b.id,
        title=b.title,
        body=b.body,
        created_by=b.created_by,
        created_at=b.created_at,
    )


# ---------------------------------------------------------------------- Routes


@router.post("/users/{user_id}/suspend", response_model=SuspensionView)
async def suspend_user(
    user_id: UUID,
    body: SuspendUserRequest,
    principal: AdminPrincipal,
    service: Service,
) -> SuspensionView:
    suspension = await service.suspend_user(
        admin_id=principal.user_id,
        user_id=user_id,
        reason_code=body.reason_code,
        note=body.note,
    )
    return suspension_view(suspension)


@router.post("/users/{user_id}/reinstate", response_model=SuspensionView)
async def reinstate_user(
    user_id: UUID,
    body: ReinstateUserRequest,
    principal: AdminPrincipal,
    service: Service,
) -> SuspensionView:
    suspension = await service.reinstate_user(
        admin_id=principal.user_id,
        user_id=user_id,
        note=body.note,
    )
    return suspension_view(suspension)


@router.get("/users/{user_id}/suspension", response_model=SuspensionView | None)
async def get_user_suspension(
    user_id: UUID,
    _: AdminPrincipal,
    service: Service,
) -> SuspensionView | None:
    suspension = await service.repo.get_active_suspension(user_id)
    return suspension_view(suspension) if suspension else None


@router.get("/listings/review", response_model=list[ListingReviewView])
async def list_listing_queue(
    _: AdminPrincipal,
    service: Service,
) -> list[ListingReviewView]:
    reviews = await service.list_pending_reviews()
    return [review_view(r) for r in reviews]


@router.post("/listings/{review_id}/approve", response_model=ListingReviewView)
async def approve_listing(
    review_id: UUID,
    body: ReviewActionRequest,
    principal: AdminPrincipal,
    service: Service,
) -> ListingReviewView:
    review = await service.approve_listing(
        admin_id=principal.user_id,
        review_id=review_id,
        note=body.note,
    )
    return review_view(review)


@router.post("/listings/{review_id}/remove", response_model=ListingReviewView)
async def remove_listing(
    review_id: UUID,
    body: ReviewActionRequest,
    principal: AdminPrincipal,
    service: Service,
) -> ListingReviewView:
    review = await service.remove_listing(
        admin_id=principal.user_id,
        review_id=review_id,
        reason=body.reason,
        note=body.note,
    )
    return review_view(review)


@router.post("/listings/report", response_model=ListingReviewView, status_code=201)
async def report_listing(
    body: ReportListingRequest,
    principal: CurrentPrincipal,
    service: Service,
) -> ListingReviewView:
    review = await service.report_listing(
        auction_id=body.auction_id,
        reported_by=principal.user_id,
        reason=body.reason,
        source="USER_REPORT",
    )
    return review_view(review)


@router.get("/audit-log")
async def get_audit_log(
    _: AdminPrincipal,
    service: Service,
    target_type: str | None = Query(default=None),
    target_id: UUID | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return await service.get_audit_log(
        target_type=target_type,
        target_id=target_id,
        actor_id=actor_id,
        limit=limit,
        offset=offset,
    )


@router.get("/metrics/daily")
async def get_daily_metrics(
    _: AdminPrincipal,
    service: Service,
) -> dict[str, Any]:
    return await service.get_daily_metrics()


@router.post("/broadcasts", response_model=BroadcastView, status_code=201)
async def create_broadcast(
    body: BroadcastRequest,
    principal: AdminPrincipal,
    service: Service,
) -> BroadcastView:
    broadcast = await service.create_broadcast(
        admin_id=principal.user_id,
        title=body.title,
        body=body.body,
    )
    return broadcast_view(broadcast)


@router.get("/broadcasts", response_model=list[BroadcastView])
async def list_broadcasts(
    _: CurrentPrincipal,
    service: Service,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[BroadcastView]:
    broadcasts = await service.repo.list_broadcasts(limit=limit)
    return [broadcast_view(b) for b in broadcasts]
