"""Public and user routes for Dispute Management (Plan 6, #84)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.domain.dispute import Dispute, DisputeEvidence
from app.service import DisputeService
from zeo_common.auth import CurrentPrincipal
from zeo_common.storage import ObjectStore, StorageError

router = APIRouter(prefix="/api/v1", tags=["disputes"])


def get_service(request: Request) -> DisputeService:
    return request.app.state.dispute_service


Service = Annotated[DisputeService, Depends(get_service)]

MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
PHOTO_TYPES = {
    "image/jpeg": ("jpg", b"\xff\xd8\xff"),
    "image/png": ("png", b"\x89PNG\r\n\x1a\n"),
    "image/webp": ("webp", b"RIFF"),
}


def get_evidence_store(request: Request) -> ObjectStore:
    return request.app.state.evidence_store


EvidenceStore = Annotated[ObjectStore, Depends(get_evidence_store)]


def detect_photo(data: bytes) -> tuple[str, str] | None:
    """Return trusted content type and extension after checking the file bytes."""
    for content_type, (extension, signature) in PHOTO_TYPES.items():
        if not data.startswith(signature):
            continue
        if content_type == "image/webp" and (len(data) < 12 or data[8:12] != b"WEBP"):
            continue
        return content_type, extension
    return None


# ---------------------------------------------------------------------- Schemas


class CreateDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: Literal[
        "ITEM_NOT_RECEIVED",
        "NOT_AS_DESCRIBED",
        "DAMAGED_IN_TRANSIT",
        "COUNTERFEIT",
        "OTHER",
    ]
    description: str = Field(min_length=1, max_length=4000)


class AddEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["PHOTO", "DOCUMENT", "SELLER_RESPONSE"]
    object_key: str | None = None
    body: str | None = None


class DisputeView(BaseModel):
    id: UUID
    order_id: UUID
    opened_by: str
    opened_by_user_id: UUID | None
    fraud_alert_id: UUID | None
    reason_code: str
    description: str
    state: str
    fault: str | None
    resolution_note: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    opened_at: datetime | None
    updated_at: datetime | None


class EvidenceView(BaseModel):
    id: UUID
    dispute_id: UUID
    kind: str
    submitted_by: UUID | None
    object_key: str | None
    bid_trace: dict | None
    body: str | None
    submitted_at: datetime | None


def dispute_view(d: Dispute) -> DisputeView:
    return DisputeView(
        id=d.id,
        order_id=d.order_id,
        opened_by=d.opened_by.value,
        opened_by_user_id=d.opened_by_user_id,
        fraud_alert_id=d.fraud_alert_id,
        reason_code=d.reason_code.value,
        description=d.description,
        state=d.state.value,
        fault=d.fault.value if d.fault else None,
        resolution_note=d.resolution_note,
        resolved_by=d.resolved_by,
        resolved_at=d.resolved_at,
        opened_at=d.opened_at,
        updated_at=d.updated_at,
    )


def evidence_view(e: DisputeEvidence) -> EvidenceView:
    return EvidenceView(
        id=e.id,
        dispute_id=e.dispute_id,
        kind=e.kind.value,
        submitted_by=e.submitted_by,
        object_key=e.object_key,
        bid_trace=e.bid_trace,
        body=e.body,
        submitted_at=e.submitted_at,
    )


# ---------------------------------------------------------------------- Routes


@router.post("/orders/{order_id}/disputes", response_model=DisputeView, status_code=201)
async def create_dispute(
    order_id: UUID,
    body: CreateDisputeRequest,
    principal: CurrentPrincipal,
    service: Service,
) -> DisputeView:
    """Buyer raises a dispute against an order (window-gated, AC-11)."""
    dispute = await service.raise_dispute(
        order_id=order_id,
        user_id=principal.user_id,
        reason_code=body.reason_code,
        description=body.description,
        is_admin=principal.is_admin,
    )
    return dispute_view(dispute)


@router.get("/orders/{order_id}/disputes", response_model=list[DisputeView])
async def list_order_disputes(
    order_id: UUID,
    principal: CurrentPrincipal,
    service: Service,
) -> list[DisputeView]:
    disputes = await service.list_order_disputes(order_id, principal.user_id, is_admin=principal.is_admin)
    return [dispute_view(d) for d in disputes]


@router.get("/disputes/{dispute_id}", response_model=DisputeView)
async def get_dispute(
    dispute_id: UUID,
    principal: CurrentPrincipal,
    service: Service,
) -> DisputeView:
    dispute = await service.require_dispute_access(dispute_id, principal.user_id, is_admin=principal.is_admin)
    return dispute_view(dispute)


@router.post("/disputes/{dispute_id}/evidence", response_model=EvidenceView, status_code=201)
async def add_evidence(
    dispute_id: UUID,
    body: AddEvidenceRequest,
    principal: CurrentPrincipal,
    service: Service,
) -> EvidenceView:
    evidence = await service.add_evidence(
        dispute_id=dispute_id,
        submitted_by=principal.user_id,
        kind=body.kind,
        object_key=body.object_key,
        body=body.body,
        is_admin=principal.is_admin,
    )
    return evidence_view(evidence)


@router.post("/disputes/{dispute_id}/evidence/upload", response_model=EvidenceView, status_code=201)
async def upload_photo_evidence(
    dispute_id: UUID,
    principal: CurrentPrincipal,
    service: Service,
    store: EvidenceStore,
    photo: UploadFile = File(...),
) -> EvidenceView:
    """Upload buyer/seller photo evidence into the private dispute-evidence bucket."""
    data = await photo.read(MAX_EVIDENCE_BYTES + 1)
    if not data:
        from zeo_common import ApiError
        raise ApiError("VALIDATION_ERROR", "Choose a photo to upload", 422)
    if len(data) > MAX_EVIDENCE_BYTES:
        from zeo_common import ApiError
        raise ApiError("VALIDATION_ERROR", "Photos must be 10 MB or smaller", 422)
    detected = detect_photo(data)
    if not detected:
        from zeo_common import ApiError
        raise ApiError("VALIDATION_ERROR", "Use a JPEG, PNG, or WebP photo", 422)
    content_type, extension = detected
    key = f"disputes/{dispute_id}/{uuid4()}.{extension}"
    try:
        await store.put(key, data, content_type)
    except StorageError as exc:
        from zeo_common import ApiError
        raise ApiError("SERVICE_UNAVAILABLE", "Evidence storage is temporarily unavailable", 503) from exc
    try:
        evidence = await service.add_evidence(
            dispute_id=dispute_id,
            submitted_by=principal.user_id,
            kind="PHOTO",
            object_key=key,
            is_admin=principal.is_admin,
        )
    except Exception:
        try:
            await store.delete(key)
        except StorageError:
            # Preserve the original authorization/database error. A lifecycle job can
            # remove this orphaned private object later if the store is unavailable.
            pass
        raise
    return evidence_view(evidence)


@router.get("/disputes/{dispute_id}/evidence", response_model=list[EvidenceView])
async def get_evidence(
    dispute_id: UUID,
    principal: CurrentPrincipal,
    service: Service,
) -> list[EvidenceView]:
    await service.require_dispute_access(dispute_id, principal.user_id, is_admin=principal.is_admin)
    evidences = await service.repo.get_evidence(dispute_id)
    return [evidence_view(e) for e in evidences]
