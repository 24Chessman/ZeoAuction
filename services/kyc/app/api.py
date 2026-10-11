"""Seller-facing KYC routes (#38; SDD 7.2; services/kyc/docs/design.md section 3).

``POST /kyc/submissions`` takes the required documents in the same multipart request, so a
submission never exists without them (guard K1). It is also how a rejected seller resubmits
(K5): a new submission row, the rejected one stays for audit. Responses carry document
metadata only, never a URL; sellers do not read documents back.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel

from app.domain.submission import Document, Submission
from app.service import KycService, Upload
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


class SubmissionView(BaseModel):
    submission_id: UUID
    state: str
    rejection_reason: str | None
    submitted_at: datetime
    decided_at: datetime | None
    can_resubmit: bool
    documents: list[DocumentView]


def document_view(document: Document) -> DocumentView:
    return DocumentView(
        document_id=document.id, doc_type=document.doc_type, mime_type=document.mime_type,
        size_bytes=document.size_bytes, uploaded_at=document.uploaded_at,
    )


def submission_view(submission: Submission, documents: list[Document]) -> SubmissionView:
    return SubmissionView(
        submission_id=submission.id,
        state=submission.state,
        rejection_reason=submission.rejection_reason,
        submitted_at=submission.submitted_at,
        decided_at=submission.decided_at,
        can_resubmit=submission.state == "REJECTED",
        documents=[document_view(d) for d in documents],
    )


async def read_upload(doc_type: str, file: UploadFile, max_bytes: int) -> Upload:
    # Read one byte past the limit so an oversized file is refused without buffering it all.
    data = await file.read(max_bytes + 1)
    return Upload(doc_type=doc_type, data=data, content_type=file.content_type)


@router.post("/kyc/submissions", status_code=201, response_model=SubmissionView)
async def submit(
    principal: CurrentPrincipal,
    service: Service,
    government_id: Annotated[UploadFile, File()],
    proof_of_address: Annotated[UploadFile, File()],
    selfie: Annotated[UploadFile | None, File()] = None,
) -> SubmissionView:
    files = {"GOVERNMENT_ID": government_id, "PROOF_OF_ADDRESS": proof_of_address,
             "SELFIE": selfie}
    uploads = [
        await read_upload(doc_type, file, service.max_document_bytes)
        for doc_type, file in files.items()
        if file is not None
    ]
    return submission_view(*await service.submit(principal, uploads))


@router.post("/kyc/submissions/{submission_id}/documents", status_code=201,
             response_model=DocumentView)
async def add_document(
    submission_id: UUID,
    principal: CurrentPrincipal,
    service: Service,
    doc_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> DocumentView:
    upload = await read_upload(doc_type, file, service.max_document_bytes)
    return document_view(await service.add_document(principal, submission_id, upload))


@router.get("/kyc/submissions/me", response_model=SubmissionView)
async def my_submission(principal: CurrentPrincipal, service: Service) -> SubmissionView:
    return submission_view(*await service.mine(principal))
