"""Admin adjudication API for Dispute Management (Plan 6, #84).

POST /api/v1/admin/disputes/{id}/resolve takes outcome and fault as separate inputs,
and derives the fee treatment automatically from the fault (SDD Table 6.3).
Every admin action writes to admin.audit_log (append-only).
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api import DisputeView, dispute_view, get_service
from app.service import DisputeService
from zeo_common.auth import AdminPrincipal

router = APIRouter(prefix="/api/v1/admin/disputes", tags=["admin-disputes"])

Service = Annotated[DisputeService, Depends(get_service)]


class ResolveDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["RESOLVED_SELLER", "RESOLVED_BUYER"]
    fault: Literal["BUYER", "SELLER", "PLATFORM"] | None = None
    note: str = Field(min_length=1, max_length=2000)


@router.get("", response_model=list[DisputeView])
async def list_admin_disputes(
    _: AdminPrincipal,
    service: Service,
    state: str | None = Query(default=None),
) -> list[DisputeView]:
    """Admin queue of disputes (pending review, open, or resolved)."""
    disputes = await service.repo.list_disputes(state=state)
    return [dispute_view(d) for d in disputes]


@router.post("/{dispute_id}/review", response_model=DisputeView)
async def start_review(
    dispute_id: UUID,
    principal: AdminPrincipal,
    service: Service,
) -> DisputeView:
    """Move dispute from OPEN to UNDER_REVIEW."""
    dispute = await service.start_review(dispute_id, principal.user_id)
    return dispute_view(dispute)


@router.post("/{dispute_id}/resolve", response_model=DisputeView)
async def resolve_dispute(
    dispute_id: UUID,
    body: ResolveDisputeRequest,
    principal: AdminPrincipal,
    service: Service,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DisputeView:
    """Adjudicate dispute: outcome and fault are separate inputs.

    - RESOLVED_SELLER -> releases escrow net payout to seller
    - RESOLVED_BUYER -> refunds buyer (fee retained if fault=BUYER; full refund if fault=SELLER/PLATFORM)
    Audited in admin.audit_log.
    """
    dispute = await service.resolve_dispute(
        dispute_id=dispute_id,
        admin_id=principal.user_id,
        outcome=body.outcome,
        fault=body.fault,
        note=body.note,
        idempotency_key=idempotency_key,
    )
    return dispute_view(dispute)
