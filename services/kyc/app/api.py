"""Seller-facing KYC routes (services/kyc/README.md).

1. ``POST /kyc/aadhaar``: a photo of the Aadhaar Secure QR (and, optionally, the mobile
   number to check against what UIDAI put in it). A verified QR creates the submission (K1,
   or K5 after a rejection).
2. ``POST /kyc/submissions/{id}/face``: 3-8 live camera frames. The match decides the
   submission on the spot, or hands it to an administrator.

Responses carry the holder's name and metadata only, never a URL, never the QR payload.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel

from app.domain.aadhaar import MAX_IMAGE_BYTES, AadhaarSummary
from app.domain.face import FaceAttempt
from app.domain.submission import Document
from app.service import KycService, SubmissionState
from zeo_common.auth import CurrentPrincipal

router = APIRouter(prefix="/api/v1", tags=["kyc"])


def get_service(request: Request) -> KycService:
    return request.app.state.kyc_service


Service = Annotated[KycService, Depends(get_service)]


class DocumentView(BaseModel):
    document_id: UUID
    doc_type: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime


class AadhaarView(BaseModel):
    holder_name: str
    year_of_birth: int
    gender: str
    state: str | None
    reference_last4: str
    qr_generated_at: datetime
    mobile_verified: bool | None


class FaceStatusView(BaseModel):
    attempts_used: int
    attempts_left: int
    last_outcome: str | None


class SubmissionView(BaseModel):
    submission_id: UUID
    state: str
    rejection_reason: str | None
    submitted_at: datetime
    decided_at: datetime | None
    can_resubmit: bool
    resubmit_after: datetime | None
    aadhaar: AadhaarView | None
    face: FaceStatusView
    documents: list[DocumentView]


class FaceCheckView(BaseModel):
    outcome: str
    attempts_left: int
    submission: SubmissionView


def document_view(document: Document) -> DocumentView:
    return DocumentView(
        document_id=document.id, doc_type=document.doc_type, mime_type=document.mime_type,
        size_bytes=document.size_bytes, uploaded_at=document.uploaded_at,
    )


def aadhaar_view(summary: AadhaarSummary) -> AadhaarView:
    return AadhaarView(
        holder_name=summary.holder_name, year_of_birth=summary.year_of_birth,
        gender=summary.gender, state=summary.state, reference_last4=summary.reference_last4,
        qr_generated_at=summary.qr_generated_at, mobile_verified=summary.mobile_verified,
    )


def face_status(attempts: list[FaceAttempt], left: int) -> FaceStatusView:
    return FaceStatusView(
        attempts_used=len(attempts), attempts_left=left,
        last_outcome=attempts[-1].outcome if attempts else None,
    )


def submission_view(state: SubmissionState) -> SubmissionView:
    submission = state.submission
    return SubmissionView(
        submission_id=submission.id,
        state=submission.state,
        rejection_reason=submission.rejection_reason,
        submitted_at=submission.submitted_at,
        decided_at=submission.decided_at,
        can_resubmit=state.can_resubmit,
        resubmit_after=state.resubmit_after,
        aadhaar=None if state.aadhaar is None else aadhaar_view(state.aadhaar),
        face=face_status(state.attempts, state.attempts_left),
        documents=[document_view(d) for d in state.documents],
    )


@router.post("/kyc/aadhaar", status_code=201, response_model=SubmissionView)
async def submit_aadhaar(
    principal: CurrentPrincipal,
    service: Service,
    qr_image: Annotated[UploadFile, File(
        description="A JPEG, PNG or WebP photo of the Aadhaar Secure QR code")],
    mobile: Annotated[str | None, Form(max_length=20)] = None,
) -> SubmissionView:
    # Read one byte past the limit so an oversized file is refused without buffering it all.
    data = await qr_image.read(MAX_IMAGE_BYTES + 1)
    return submission_view(await service.submit_aadhaar(principal, data, mobile))


@router.post("/kyc/submissions/{submission_id}/face", response_model=FaceCheckView)
async def face_check(
    submission_id: UUID,
    principal: CurrentPrincipal,
    service: Service,
    frames: Annotated[list[UploadFile], File(description="3-8 JPEG or PNG camera frames")],
) -> FaceCheckView:
    limit = service.max_frame_bytes + 1
    data = [await frame.read(limit) for frame in frames[: service.policy.max_frames + 1]]
    result = await service.face_check(principal, submission_id, data)
    return FaceCheckView(
        outcome=result.outcome, attempts_left=result.state.attempts_left,
        submission=submission_view(result.state),
    )


@router.get("/kyc/submissions/me", response_model=SubmissionView)
async def my_submission(principal: CurrentPrincipal, service: Service) -> SubmissionView:
    return submission_view(await service.mine(principal))
