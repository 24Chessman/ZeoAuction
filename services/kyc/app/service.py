"""KYC use cases: submit, add a document, read my status, and the admin review actions.

Upload order: validate every file -> store the bytes -> commit the rows. If the commit fails,
the stored objects are removed again, so the bucket never holds documents no row points to
for long. After a commit that changed the user's status, the new ``token_version`` is
announced (forced token refresh, design.md section 5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.adapters.document_store import DocumentStore
from app.adapters.kyc_repo import (
    ActiveSubmissionExists,
    DocumentTypeExists,
    KycRepository,
    StaleSubmission,
)
from app.adapters.user_mirror import TokenRefreshAnnouncer, UnknownUser
from app.domain.submission import (
    Document,
    DocumentInvalid,
    Submission,
    ValidatedUpload,
    new_document,
    require_documents,
    validate_upload,
)
from app.domain.verification import (
    IllegalTransition,
    ReasonRequired,
    can_submit,
    plan_transition,
    submit_transition,
)
from zeo_common import ApiError, get_request_id
from zeo_common.auth import Principal
from zeo_common.storage import StorageError


@dataclass(frozen=True)
class Upload:
    doc_type: str
    data: bytes
    content_type: str | None


def document_invalid(error: DocumentInvalid) -> ApiError:
    return ApiError(
        "DOCUMENT_INVALID", str(error), 422,
        {"doc_type": error.doc_type, "reason": error.reason},
    )


def storage_unavailable() -> ApiError:
    return ApiError(
        "SERVICE_UNAVAILABLE", "Document storage is unavailable; nothing was saved, retry", 503
    )


def request_uuid() -> UUID | None:
    try:
        return UUID(get_request_id())
    except (ValueError, TypeError):
        return None


class KycService:
    def __init__(
        self,
        repo: KycRepository,
        documents: DocumentStore,
        announcer: TokenRefreshAnnouncer,
        *,
        max_document_bytes: int,
        retention_days: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.documents = documents
        self.announcer = announcer
        self.max_document_bytes = max_document_bytes
        self.retention_days = retention_days
        self.clock = clock

    def _validate(self, upload: Upload) -> ValidatedUpload:
        try:
            return validate_upload(upload.doc_type, upload.data, upload.content_type,
                                   self.max_document_bytes)
        except DocumentInvalid as exc:
            raise document_invalid(exc) from exc

    async def _store(self, pairs: list[tuple[Document, ValidatedUpload]]) -> None:
        saved: list[Document] = []
        try:
            for document, upload in pairs:
                await self.documents.save(document, upload)
                saved.append(document)
        except StorageError as exc:
            await self.documents.discard(saved)
            raise storage_unavailable() from exc

    # ------------------------------------------------------------------ seller

    async def submit(
        self, principal: Principal, uploads: list[Upload]
    ) -> tuple[Submission, list[Document]]:
        """K1, or K5 when the latest submission was rejected (a new row; the old one stays)."""
        validated = [self._validate(upload) for upload in uploads]
        try:
            require_documents(validated)
        except DocumentInvalid as exc:
            raise document_invalid(exc) from exc
        latest = await self.repo.latest_for_user(principal.user_id)
        if not can_submit(latest):
            raise kyc_already_active(latest)
        now = self.clock()
        submission = Submission(
            id=uuid4(), user_id=principal.user_id, state="SUBMITTED", rejection_reason=None,
            submitted_at=now, decided_at=None, decided_by=None, updated_at=now,
        )
        pairs = [
            (new_document(upload, doc_id=uuid4(), submission=submission, now=now,
                          retention_days=self.retention_days), upload)
            for upload in validated
        ]
        await self._store(pairs)
        stored = [document for document, _ in pairs]
        try:
            version = await self.repo.create(
                submission, stored, submit_transition(submission, now, latest)
            )
        except ActiveSubmissionExists as exc:
            await self.documents.discard(stored)
            raise kyc_already_active(None) from exc
        except BaseException:
            await self.documents.discard(stored)
            raise
        await self.announcer.announce(principal.user_id, version)
        return submission, stored

    async def add_document(self, principal: Principal, submission_id: UUID,
                           upload: Upload) -> Document:
        """Add a document type the submission lacks (for example the optional SELFIE) while
        it is still waiting for review. It does not change the state."""
        submission = await self.repo.get(submission_id)
        if submission is None or submission.user_id != principal.user_id:
            raise ApiError("NOT_FOUND", "Submission not found", 404)
        if submission.state != "SUBMITTED":
            raise ApiError(
                "CONFLICT", "Documents can only be added before review starts", 409,
                {"state": submission.state},
            )
        validated = self._validate(upload)
        document = new_document(validated, doc_id=uuid4(), submission=submission,
                                now=self.clock(), retention_days=self.retention_days)
        await self._store([(document, validated)])
        try:
            await self.repo.add_document(document)
        except DocumentTypeExists as exc:
            await self.documents.discard([document])
            raise ApiError(
                "CONFLICT", f"A {document.doc_type} document was already uploaded", 409,
                {"doc_type": document.doc_type},
            ) from exc
        except BaseException:
            await self.documents.discard([document])
            raise
        return document

    async def mine(self, principal: Principal) -> tuple[Submission, list[Document]]:
        latest = await self.repo.latest_for_user(principal.user_id)
        if latest is None:
            raise ApiError("NOT_FOUND", "No KYC submission yet", 404,
                           {"kyc_status": "NOT_SUBMITTED"})
        return latest, await self.repo.documents(latest.id)

    # ------------------------------------------------------------------ admin

    async def detail(self, submission_id: UUID) -> tuple[Submission, list[Document]]:
        submission = await self.repo.get(submission_id)
        if submission is None:
            raise ApiError("NOT_FOUND", "Submission not found", 404)
        return submission, await self.repo.documents(submission_id)

    async def queue(self, states: tuple[str, ...], limit: int, offset: int) -> list[Submission]:
        return await self.repo.queue(states, limit, offset)

    async def transition(self, admin: Principal, submission_id: UUID, event: str,
                         reason: str | None = None) -> Submission:
        submission, _ = await self.detail(submission_id)
        try:
            transition, updated = plan_transition(
                submission, event, actor_id=admin.user_id, reason=reason, now=self.clock()
            )
            version = await self.repo.apply(transition, updated, admin.role, request_uuid())
        except IllegalTransition as exc:
            raise ApiError(
                "CONFLICT", str(exc), 409, {"state": exc.state, "event": exc.event}
            ) from exc
        except ReasonRequired as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": "reason"}) from exc
        except StaleSubmission as exc:
            raise ApiError(
                "CONFLICT", "The submission changed concurrently; reload it", 409
            ) from exc
        except UnknownUser as exc:
            raise ApiError("CONFLICT", "The submission's account no longer exists", 409) from exc
        await self.announcer.announce(updated.user_id, version)
        return updated

    async def document_url(self, admin: Principal, submission_id: UUID,
                           document_id: UUID) -> tuple[str, int]:
        """A fresh signed URL per view; the view itself is audited (SDD Fig. 8.8)."""
        _, documents = await self.detail(submission_id)
        document = next((d for d in documents if d.id == document_id), None)
        if document is None:
            raise ApiError("NOT_FOUND", "Document not found", 404)
        await self.repo.audit_document_view(admin.user_id, admin.role, document, request_uuid())
        return self.documents.view_url(document), self.documents.url_ttl_seconds


def kyc_already_active(latest: Submission | None) -> ApiError:
    details = {"state": latest.state} if latest is not None else None
    return ApiError(
        "KYC_ALREADY_ACTIVE",
        "A KYC submission is already in progress or approved; resubmit only after a rejection",
        409, details,
    )
