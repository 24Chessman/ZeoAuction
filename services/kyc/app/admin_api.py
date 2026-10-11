"""Admin KYC review queue (#80; SDD 7.2, Fig. 8.8; design.md section 3).

Every route needs the ``ADMIN`` role. Approve, reject, suspend and reinstate are transitions
K3, K4, K6 and K7; each is audited in ``admin.audit_log`` and forces the seller's token to be
refreshed. Opening a document returns a signed URL valid for 60 seconds, and the view itself
is audited. These routes live here, not in admin-moderation, because they write KYC rows.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from app.api import DocumentView, Service, document_view
from app.domain.submission import Document, Submission
from zeo_common.auth import AdminPrincipal

router = APIRouter(prefix="/api/v1/admin/kyc", tags=["admin-kyc"])

QueueState = Literal["SUBMITTED", "UNDER_REVIEW"]


class AdminDocumentView(DocumentView):
    sha256: str


class AdminSubmissionView(BaseModel):
    submission_id: UUID
    user_id: UUID
    state: str
    rejection_reason: str | None
    submitted_at: datetime
    decided_at: datetime | None
    decided_by: UUID | None
    documents: list[AdminDocumentView]


class QueueItem(BaseModel):
    submission_id: UUID
    user_id: UUID
    state: str
    submitted_at: datetime


class QueuePage(BaseModel):
    items: list[QueueItem]
    limit: int
    offset: int


class RejectRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class SuspendRequest(BaseModel):
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,39}$", examples=["DOCUMENT_FORGERY"])


class DocumentUrl(BaseModel):
    url: str
    expires_in: int


def admin_document_view(document: Document) -> AdminDocumentView:
    return AdminDocumentView(**document_view(document).model_dump(), sha256=document.sha256)


def admin_view(submission: Submission, documents: list[Document]) -> AdminSubmissionView:
    return AdminSubmissionView(
        submission_id=submission.id, user_id=submission.user_id, state=submission.state,
        rejection_reason=submission.rejection_reason, submitted_at=submission.submitted_at,
        decided_at=submission.decided_at, decided_by=submission.decided_by,
        documents=[admin_document_view(d) for d in documents],
    )


@router.get("/queue", response_model=QueuePage)
async def review_queue(
    admin: AdminPrincipal,
    service: Service,
    state: Annotated[list[QueueState] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QueuePage:
    """Waiting submissions, oldest first. Defaults to both waiting states."""
    states = tuple(state or ("SUBMITTED", "UNDER_REVIEW"))
    items = await service.queue(states, limit, offset)
    return QueuePage(
        items=[QueueItem(submission_id=s.id, user_id=s.user_id, state=s.state,
                         submitted_at=s.submitted_at) for s in items],
        limit=limit, offset=offset,
    )


@router.get("/{submission_id}", response_model=AdminSubmissionView)
async def submission_detail(submission_id: UUID, admin: AdminPrincipal,
                            service: Service) -> AdminSubmissionView:
    return admin_view(*await service.detail(submission_id))


async def _transition(service, admin, submission_id, event, reason=None) -> AdminSubmissionView:
    updated = await service.transition(admin, submission_id, event, reason)
    _, documents = await service.detail(submission_id)
    return admin_view(updated, documents)


@router.post("/{submission_id}/start-review", response_model=AdminSubmissionView)
async def start_review(submission_id: UUID, admin: AdminPrincipal,
                       service: Service) -> AdminSubmissionView:
    return await _transition(service, admin, submission_id, "startReview")


@router.post("/{submission_id}/approve", response_model=AdminSubmissionView)
async def approve(submission_id: UUID, admin: AdminPrincipal,
                  service: Service) -> AdminSubmissionView:
    return await _transition(service, admin, submission_id, "approve")


@router.post("/{submission_id}/reject", response_model=AdminSubmissionView)
async def reject(submission_id: UUID, body: RejectRequest, admin: AdminPrincipal,
                 service: Service) -> AdminSubmissionView:
    return await _transition(service, admin, submission_id, "reject", body.reason)


@router.post("/{submission_id}/suspend", response_model=AdminSubmissionView)
async def suspend(submission_id: UUID, body: SuspendRequest, admin: AdminPrincipal,
                  service: Service) -> AdminSubmissionView:
    return await _transition(service, admin, submission_id, "suspend", body.reason_code)


@router.post("/{submission_id}/reinstate", response_model=AdminSubmissionView)
async def reinstate(submission_id: UUID, admin: AdminPrincipal,
                    service: Service) -> AdminSubmissionView:
    return await _transition(service, admin, submission_id, "reinstate")


@router.get("/{submission_id}/documents/{document_id}/url", response_model=DocumentUrl)
async def document_url(submission_id: UUID, document_id: UUID, admin: AdminPrincipal,
                       service: Service, response: Response) -> DocumentUrl:
    url, ttl = await service.document_url(admin, submission_id, document_id)
    response.headers["Cache-Control"] = "no-store"
    return DocumentUrl(url=url, expires_in=ttl)
