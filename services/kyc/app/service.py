"""KYC use cases: verify an Aadhaar Secure QR, read seller status, and admin review actions.

Upload order: verify everything -> store the images -> commit the rows. If the commit fails,
the stored objects are removed again, so the bucket never holds images no row points to for
long. After a commit that changed the user's status, the new ``token_version`` is announced
(forced token refresh, services/kyc/README.md).

Privacy: the QR photo, its decoded payload and the mobile number live only for the request.
Nothing here logs them; log lines carry ids only.
"""

import asyncio
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.adapters.document_store import DocumentStore
from app.adapters.kyc_repo import ActiveSubmissionExists, KycRepository, StaleSubmission
from app.adapters.qr_reader import QrReader
from app.adapters.user_mirror import TokenRefreshAnnouncer, UnknownUser
from app.domain.aadhaar import (
    AadhaarInvalid,
    AadhaarSummary,
    TrustedKey,
    check_image,
    read_secure_qr,
)
from app.domain.submission import (
    Document,
    Submission,
    ValidatedUpload,
    new_document,
)
from app.domain.verification import (
    IllegalTransition,
    ReasonRequired,
    plan_transition,
    submit_transition,
)
from zeo_common import ApiError, get_request_id
from zeo_common.auth import Principal
from zeo_common.storage import StorageError


@dataclass(frozen=True)
class SubmissionState:
    """A submission with everything the views show about it."""

    submission: Submission
    documents: list[Document]
    aadhaar: AadhaarSummary | None
    attempts: list
    can_resubmit: bool
    resubmit_after: datetime | None
    attempts_left: int


def storage_unavailable() -> ApiError:
    return ApiError(
        "SERVICE_UNAVAILABLE", "Document storage is unavailable; nothing was saved, retry", 503
    )


def request_uuid() -> UUID | None:
    try:
        return UUID(get_request_id())
    except (ValueError, TypeError):
        return None


def aadhaar_invalid(error: AadhaarInvalid) -> ApiError:
    return ApiError(
        "AADHAAR_INVALID", str(error), 422, {"reason": error.reason, "field": error.field}
    )


class KycService:
    def __init__(
        self,
        repo: KycRepository,
        documents: DocumentStore,
        announcer: TokenRefreshAnnouncer,
        qr_reader: QrReader,
        *,
        trusted_keys: Sequence[TrustedKey],
        aadhaar_max_age: timedelta | None,
        retention_days: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.documents = documents
        self.announcer = announcer
        self.qr_reader = qr_reader
        self.trusted_keys = tuple(trusted_keys)
        self.aadhaar_max_age = aadhaar_max_age
        self.retention_days = retention_days
        self.clock = clock

    async def _store(self, pairs: list[tuple[Document, ValidatedUpload]]) -> None:
        saved: list[Document] = []
        try:
            for document, upload in pairs:
                await self.documents.save(document, upload)
                saved.append(document)
        except StorageError as exc:
            await self.documents.discard(saved)
            raise storage_unavailable() from exc

    async def _state(self, submission: Submission) -> SubmissionState:
        can, after = self._resubmission(submission)
        return SubmissionState(
            submission=submission,
            documents=await self.repo.documents(submission.id),
            aadhaar=await self.repo.aadhaar(submission.id),
            attempts=[],
            can_resubmit=can,
            resubmit_after=after,
            attempts_left=0,
        )

    def _resubmission(self, latest: Submission | None) -> tuple[bool, datetime | None]:
        """Whether a new Aadhaar upload is accepted now, and from when if not yet.

        - none yet, or rejected by an administrator or withdrawn: yes (K1, K5);
        - a submission in review, verified or suspended: no;
        - rejected submissions can be replaced;
        """
        if latest is None:
            return True, None
        if latest.state == "REJECTED":
            return True, None
        return False, None

    # ------------------------------------------------------------------ seller

    async def submit_aadhaar(
        self, principal: Principal, image: bytes, mobile: str | None
    ) -> SubmissionState:
        """K1 or K5: read and verify the Secure QR in the photo, keep the holder's photo and
        summary, then wait for administrator approval."""
        latest = await self.repo.latest_for_user(principal.user_id)
        allowed, after = self._resubmission(latest)
        if not allowed:
            raise kyc_blocked(latest, after)
        now = self.clock()
        try:
            check_image(image)
            texts = await asyncio.to_thread(self.qr_reader.read, image)
            if texts is None:
                raise AadhaarInvalid("not_image", "The photo could not be opened")
            qr = read_secure_qr(
                texts, self.trusted_keys, now=now, max_age=self.aadhaar_max_age,
                mobile=mobile or None,
            )
        except AadhaarInvalid as exc:
            raise aadhaar_invalid(exc) from exc
        submission = Submission(
            id=uuid4(), user_id=principal.user_id, state="UNDER_REVIEW", rejection_reason=None,
            submitted_at=now, decided_at=None, decided_by=None, updated_at=now,
        )
        photo = ValidatedUpload(
            doc_type="AADHAAR_PHOTO", mime_type="image/jpeg", extension="jpg",
            data=qr.photo, sha256=hashlib.sha256(qr.photo).hexdigest(),
        )
        document = new_document(photo, doc_id=uuid4(), submission=submission, now=now,
                                retention_days=self.retention_days)
        summary = AadhaarSummary(
            submission_id=submission.id, reference_last4=qr.reference_last4,
            qr_generated_at=qr.generated_at, signer_sha256=qr.signer,
            holder_name=qr.name, year_of_birth=qr.year_of_birth, gender=qr.gender,
            state=qr.state, pincode=qr.pincode, mobile_verified=qr.mobile_verified,
            face_model="disabled", reference_faces=0, reference_embedding=None, verified_at=now,
        )
        await self._store([(document, photo)])
        try:
            version = await self.repo.create(
                submission, [document], submit_transition(submission, now, latest), summary
            )
        except ActiveSubmissionExists as exc:
            await self.documents.discard([document])
            raise kyc_blocked(None, None) from exc
        except BaseException:
            await self.documents.discard([document])
            raise
        await self.announcer.announce(principal.user_id, version)
        return await self._state(submission)

    async def mine(self, principal: Principal) -> SubmissionState:
        latest = await self.repo.latest_for_user(principal.user_id)
        if latest is None:
            raise ApiError("NOT_FOUND", "No KYC submission yet", 404,
                           {"kyc_status": "NOT_SUBMITTED"})
        return await self._state(latest)

    # ------------------------------------------------------------------ admin

    async def detail(self, submission_id: UUID) -> SubmissionState:
        submission = await self.repo.get(submission_id)
        if submission is None:
            raise ApiError("NOT_FOUND", "Submission not found", 404)
        return await self._state(submission)

    async def queue(self, states: tuple[str, ...], limit: int, offset: int) -> list[Submission]:
        return await self.repo.queue(states, limit, offset)

    async def _apply(self, submission: Submission, event: str, *, actor: Principal,
                     reason: str | None) -> Submission:
        try:
            transition, updated = plan_transition(
                submission, event, actor_id=actor.user_id, reason=reason, now=self.clock()
            )
            version = await self.repo.apply(transition, updated, actor.role, request_uuid())
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

    async def transition(self, admin: Principal, submission_id: UUID, event: str,
                         reason: str | None = None) -> SubmissionState:
        current = await self.detail(submission_id)
        updated = await self._apply(current.submission, event, actor=admin, reason=reason)
        return await self._state(updated)

    async def document_url(self, admin: Principal, submission_id: UUID,
                           document_id: UUID) -> tuple[str, int]:
        """A fresh signed URL per view; the view itself is audited (SDD Fig. 8.8)."""
        current = await self.detail(submission_id)
        document = next((d for d in current.documents if d.id == document_id), None)
        if document is None:
            raise ApiError("NOT_FOUND", "Document not found", 404)
        await self.repo.audit_document_view(admin.user_id, admin.role, document, request_uuid())
        return self.documents.view_url(document), self.documents.url_ttl_seconds


def kyc_blocked(latest: Submission | None, retry_after: datetime | None) -> ApiError:
    if retry_after is not None:
        return ApiError(
            "KYC_COOLDOWN",
            "The face check failed too many times; you can try again later",
            409, {"retry_after": retry_after.isoformat()},
        )
    details = {"state": latest.state} if latest is not None else None
    return ApiError(
        "KYC_ALREADY_ACTIVE",
        "A verification is already in progress or approved",
        409, details,
    )

