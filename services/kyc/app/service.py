"""KYC use cases: verify an Aadhaar Secure QR, run the live face check, read my status,
and the admin review actions.

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
from app.adapters.face_engine import FaceEngine
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
from app.domain.face import (
    COUNTED_OUTCOMES,
    FaceAttempt,
    FaceCaptureInvalid,
    FacePolicy,
    assess,
    attempts_left,
    check_frame_count,
    counted,
    event_for,
)
from app.domain.submission import (
    Document,
    ImageInvalid,
    Submission,
    ValidatedUpload,
    new_document,
    validate_image,
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
    attempts: list[FaceAttempt]
    can_resubmit: bool
    resubmit_after: datetime | None
    attempts_left: int


@dataclass(frozen=True)
class FaceCheck:
    outcome: str
    state: SubmissionState


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


def face_capture_invalid(reason: str, message: str) -> ApiError:
    return ApiError("FACE_CAPTURE_INVALID", message, 422, {"reason": reason, "field": "frames"})


class KycService:
    def __init__(
        self,
        repo: KycRepository,
        documents: DocumentStore,
        announcer: TokenRefreshAnnouncer,
        engine: FaceEngine,
        qr_reader: QrReader,
        *,
        trusted_keys: Sequence[TrustedKey],
        aadhaar_max_age: timedelta | None,
        face_policy: FacePolicy,
        max_frame_bytes: int,
        retention_days: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.documents = documents
        self.announcer = announcer
        self.engine = engine
        self.qr_reader = qr_reader
        self.trusted_keys = tuple(trusted_keys)
        self.aadhaar_max_age = aadhaar_max_age
        self.policy = face_policy
        self.max_frame_bytes = max_frame_bytes
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
        attempts = await self.repo.face_attempts(submission.id)
        can, after = self._resubmission(submission, attempts)
        return SubmissionState(
            submission=submission,
            documents=await self.repo.documents(submission.id),
            aadhaar=await self.repo.aadhaar(submission.id),
            attempts=attempts,
            can_resubmit=can,
            resubmit_after=after,
            attempts_left=attempts_left(attempts, self.policy),
        )

    def _resubmission(self, latest: Submission | None,
                      attempts: list[FaceAttempt]) -> tuple[bool, datetime | None]:
        """Whether a new Aadhaar upload is accepted now, and from when if not yet.

        - none yet, or rejected by an administrator or withdrawn: yes (K1, K5);
        - rejected by the face check: after the cooldown, so failed matches can't be retried
          endlessly;
        - waiting for the face check: only before any counted attempt (K4b replaces it);
        - under review, verified or suspended: no.
        """
        if latest is None:
            return True, None
        if latest.state == "REJECTED":
            if counted(attempts) >= self.policy.max_attempts and latest.decided_at:
                after = latest.decided_at + self.policy.cooldown
                return (self.clock() >= after), (after if self.clock() < after else None)
            return True, None
        if latest.state == "SUBMITTED":
            return counted(attempts) == 0, None
        return False, None

    # ------------------------------------------------------------------ seller

    async def submit_aadhaar(
        self, principal: Principal, image: bytes, mobile: str | None
    ) -> SubmissionState:
        """K1 or K5: read and verify the Secure QR in the photo, keep the holder's photo and
        summary, wait for the face."""
        latest = await self.repo.latest_for_user(principal.user_id)
        attempts = [] if latest is None else await self.repo.face_attempts(latest.id)
        allowed, after = self._resubmission(latest, attempts)
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
        reference = await asyncio.to_thread(self.engine.reference, qr.photo)
        if reference.jpeg is None:
            raise aadhaar_invalid(
                AadhaarInvalid("no_photo", "The photo in the QR code could not be read"))

        if latest is not None and latest.state == "SUBMITTED":
            await self._apply(latest, "withdraw", actor=principal, reason=None)

        submission = Submission(
            id=uuid4(), user_id=principal.user_id, state="SUBMITTED", rejection_reason=None,
            submitted_at=now, decided_at=None, decided_by=None, updated_at=now,
        )
        photo = ValidatedUpload(
            doc_type="AADHAAR_PHOTO", mime_type="image/jpeg", extension="jpg",
            data=reference.jpeg, sha256=hashlib.sha256(reference.jpeg).hexdigest(),
        )
        document = new_document(photo, doc_id=uuid4(), submission=submission, now=now,
                                retention_days=self.retention_days)
        summary = AadhaarSummary(
            submission_id=submission.id, reference_last4=qr.reference_last4,
            qr_generated_at=qr.generated_at, signer_sha256=qr.signer,
            holder_name=qr.name, year_of_birth=qr.year_of_birth, gender=qr.gender,
            state=qr.state, pincode=qr.pincode, mobile_verified=qr.mobile_verified,
            face_model=self.engine.model, reference_faces=reference.faces,
            reference_embedding=reference.embedding, verified_at=now,
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

    async def face_check(self, principal: Principal, submission_id: UUID,
                         frames: list[bytes]) -> FaceCheck:
        """One attempt of the live face check against the Aadhaar photo (K2, K3a, K4a)."""
        submission = await self.repo.get(submission_id)
        if submission is None or submission.user_id != principal.user_id:
            raise ApiError("NOT_FOUND", "Submission not found", 404)
        if submission.state != "SUBMITTED":
            raise ApiError(
                "CONFLICT", "The face check is only open while the submission is waiting", 409,
                {"state": submission.state},
            )
        try:
            check_frame_count(len(frames), self.policy)
            images = [validate_image("FACE_CAPTURE", frame, self.max_frame_bytes)
                      for frame in frames]
        except (FaceCaptureInvalid, ImageInvalid) as exc:
            raise face_capture_invalid(exc.reason, str(exc)) from exc
        aadhaar = await self.repo.aadhaar(submission.id)
        attempts = await self.repo.face_attempts(submission.id)
        if aadhaar is None:
            raise ApiError("CONFLICT", "The submission has no verified Aadhaar", 409)

        readings = await asyncio.to_thread(
            self.engine.compare, aadhaar.reference_embedding, [i.data for i in images]
        )
        assessment = assess(
            readings,
            reference_usable=aadhaar.reference_embedding is not None,
            duplicate_frames=len({i.sha256 for i in images}) < len(images),
            policy=self.policy,
        )
        now = self.clock()
        attempt = FaceAttempt(
            submission_id=submission.id, attempt_no=len(attempts) + 1, frames=assessment.frames,
            good_frames=assessment.good_frames, median_score=assessment.median_score,
            min_score=assessment.min_score, yaw_span=assessment.yaw_span,
            outcome=assessment.outcome, at=now,
        )
        counted_after = counted(attempts) + (assessment.outcome in COUNTED_OUTCOMES)
        event = event_for(assessment.outcome, counted_after, self.policy)
        change = None if event is None else plan_transition(
            submission, event, actor_id=principal.user_id, reason=self._reason(assessment),
            now=now,
        )
        # The best frame is evidence for a match or for the reviewer; a failed one isn't kept.
        evidence: list[tuple[Document, ValidatedUpload]] = []
        if event in ("faceMatch", "faceReview") and assessment.best_frame is not None:
            best = images[assessment.best_frame]
            evidence.append((new_document(best, doc_id=uuid4(), submission=submission, now=now,
                                          retention_days=self.retention_days), best))
        await self._store(evidence)
        stored = [document for document, _ in evidence]
        try:
            version = await self.repo.record_face_attempt(attempt, stored, change)
        except StaleSubmission as exc:
            await self.documents.discard(stored)
            raise ApiError(
                "CONFLICT", "Another face check for this submission is in progress", 409
            ) from exc
        except BaseException:
            await self.documents.discard(stored)
            raise
        if version is not None:
            await self.announcer.announce(principal.user_id, version)
        current = change[1] if change is not None else submission
        return FaceCheck(outcome=assessment.outcome, state=await self._state(current))

    @staticmethod
    def _reason(assessment) -> str | None:
        if assessment.median_score is None:
            return f"face check {assessment.outcome}"
        return f"face check {assessment.outcome}, median similarity {assessment.median_score:.3f}"

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
