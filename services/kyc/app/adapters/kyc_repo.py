"""KYC persistence (role ``kyc_svc``): PostgreSQL for real, in-memory for tests.

Each accepted transition is one transaction (docs/state-machines.md section 3):
1. ``UPDATE kyc.kyc_submissions ... WHERE id = $1 AND state = $from``; 0 rows means someone else
   won the race (:class:`StaleSubmission`);
2. a row in the append-only ``kyc_state_transitions``;
3. the ``auth.users`` mirror with a ``token_version`` bump;
4. an ``admin.audit_log`` row for administrator actions.

A face attempt is recorded in the same transaction as the transition it causes, so a counted
attempt and a rejection can never be split. ``(submission_id, attempt_no)`` is unique, which
also catches two attempts sent at once.
"""

import json
from typing import Any, Protocol
from uuid import UUID

from app.adapters.user_mirror import InMemoryUserMirror, mirror_status
from app.domain.aadhaar import AadhaarSummary
from app.domain.submission import Document, FaceAttempt, Submission
from app.domain.verification import DOC_VIEW_ACTION, Transition

SERVICE = "kyc"
_SUBMISSION_COLUMNS = (
    "id, user_id, state, rejection_reason, submitted_at, decided_at, decided_by, updated_at"
)
_DOCUMENT_COLUMNS = (
    "id, submission_id, doc_type, object_key, mime_type, size_bytes, sha256, uploaded_at, "
    "purge_after"
)
_AADHAAR_COLUMNS = (
    "submission_id, reference_last4, qr_generated_at, signer_sha256, holder_name, "
    "year_of_birth, gender, state, pincode, mobile_verified, face_model, reference_faces, "
    "reference_embedding, verified_at"
)
_ATTEMPT_COLUMNS = (
    "submission_id, attempt_no, frames, good_frames, median_score, min_score, yaw_span, "
    "outcome, at"
)


class StaleSubmission(Exception):
    """The row was not in the expected state any more; re-read and re-evaluate."""


class ActiveSubmissionExists(Exception):
    """The user already has a live (non-rejected) submission."""


class KycRepository(Protocol):
    async def latest_for_user(self, user_id: UUID) -> Submission | None: ...

    async def get(self, submission_id: UUID) -> Submission | None: ...

    async def documents(self, submission_id: UUID) -> list[Document]: ...

    async def aadhaar(self, submission_id: UUID) -> AadhaarSummary | None: ...

    async def face_attempts(self, submission_id: UUID) -> list[FaceAttempt]: ...

    async def create(
        self, submission: Submission, documents: list[Document], transition: Transition,
        aadhaar: AadhaarSummary,
    ) -> int: ...

    async def record_face_attempt(
        self, attempt: FaceAttempt, documents: list[Document],
        change: tuple[Transition, Submission] | None,
    ) -> int | None: ...

    async def apply(self, transition: Transition, updated: Submission, actor_role: str,
                    request_id: UUID | None) -> int: ...

    async def queue(self, states: tuple[str, ...], limit: int, offset: int) -> list[Submission]: ...

    async def audit_document_view(self, actor_id: UUID, actor_role: str, document: Document,
                                  request_id: UUID | None) -> None: ...


def _audit_row(transition: Transition, actor_role: str, request_id: UUID | None) -> tuple:
    reason_code = transition.reason if transition.event == "suspend" else None
    note = transition.reason if transition.event == "reject" else None
    return (
        transition.actor_id, actor_role, SERVICE, transition.audit_action, "KYC_SUBMISSION",
        transition.submission_id,
        json.dumps({"state": transition.from_state}), json.dumps({"state": transition.to_state}),
        reason_code, note, request_id, transition.at,
    )


def _aadhaar_args(summary: AadhaarSummary) -> tuple:
    embedding = None if summary.reference_embedding is None else list(summary.reference_embedding)
    return (
        summary.submission_id, summary.reference_last4, summary.qr_generated_at,
        summary.signer_sha256, summary.holder_name, summary.year_of_birth, summary.gender,
        summary.state, summary.pincode, summary.mobile_verified, summary.face_model,
        summary.reference_faces, embedding, summary.verified_at,
    )


def _aadhaar_from_row(row: Any) -> AadhaarSummary:
    values = dict(row)
    embedding = values.pop("reference_embedding")
    return AadhaarSummary(
        **values, reference_embedding=None if embedding is None else tuple(embedding)
    )


def _attempt_args(attempt: FaceAttempt) -> tuple:
    return (
        attempt.submission_id, attempt.attempt_no, attempt.frames, attempt.good_frames,
        attempt.median_score, attempt.min_score, attempt.yaw_span, attempt.outcome, attempt.at,
    )


class InMemoryKycRepository:
    def __init__(self, mirror: InMemoryUserMirror | None = None) -> None:
        self.submissions: dict[UUID, Submission] = {}
        self.docs: dict[UUID, Document] = {}
        self.aadhaar_rows: dict[UUID, AadhaarSummary] = {}
        self.attempts: list[FaceAttempt] = []
        self.transitions: list[Transition] = []
        self.audit_log: list[tuple] = []
        self.mirror = mirror or InMemoryUserMirror()

    async def latest_for_user(self, user_id: UUID) -> Submission | None:
        mine = [s for s in self.submissions.values() if s.user_id == user_id]
        return max(mine, key=lambda s: s.submitted_at, default=None)

    async def get(self, submission_id: UUID) -> Submission | None:
        return self.submissions.get(submission_id)

    async def documents(self, submission_id: UUID) -> list[Document]:
        found = [d for d in self.docs.values() if d.submission_id == submission_id]
        return sorted(found, key=lambda d: (d.uploaded_at, d.doc_type))

    async def aadhaar(self, submission_id: UUID) -> AadhaarSummary | None:
        return self.aadhaar_rows.get(submission_id)

    async def face_attempts(self, submission_id: UUID) -> list[FaceAttempt]:
        return sorted((a for a in self.attempts if a.submission_id == submission_id),
                      key=lambda a: a.attempt_no)

    async def create(
        self, submission: Submission, documents: list[Document], transition: Transition,
        aadhaar: AadhaarSummary,
    ) -> int:
        if any(s.user_id == submission.user_id and s.state != "REJECTED"
               for s in self.submissions.values()):
            raise ActiveSubmissionExists(str(submission.user_id))
        self.submissions[submission.id] = submission
        for document in documents:
            self.docs[document.id] = document
        self.aadhaar_rows[submission.id] = aadhaar
        self.transitions.append(transition)
        return self.mirror.mirror(submission.user_id, transition.to_state)

    async def record_face_attempt(
        self, attempt: FaceAttempt, documents: list[Document],
        change: tuple[Transition, Submission] | None,
    ) -> int | None:
        if any(a.submission_id == attempt.submission_id and a.attempt_no == attempt.attempt_no
               for a in self.attempts):
            raise StaleSubmission(str(attempt.submission_id))
        if change is not None:
            transition, updated = change
            current = self.submissions.get(transition.submission_id)
            if current is None or current.state != transition.from_state:
                raise StaleSubmission(str(transition.submission_id))
        self.attempts.append(attempt)
        for document in documents:
            self.docs[document.id] = document
        if change is None:
            return None
        self.submissions[updated.id] = updated
        self.transitions.append(transition)
        return self.mirror.mirror(updated.user_id, transition.to_state)

    async def apply(self, transition: Transition, updated: Submission, actor_role: str,
                    request_id: UUID | None) -> int:
        current = self.submissions.get(transition.submission_id)
        if current is None or current.state != transition.from_state:
            raise StaleSubmission(str(transition.submission_id))
        self.submissions[updated.id] = updated
        self.transitions.append(transition)
        if transition.audit_action:
            self.audit_log.append(_audit_row(transition, actor_role, request_id))
        return self.mirror.mirror(updated.user_id, transition.to_state)

    async def queue(self, states: tuple[str, ...], limit: int, offset: int) -> list[Submission]:
        waiting = sorted(
            (s for s in self.submissions.values() if s.state in states),
            key=lambda s: (s.submitted_at, str(s.id)),
        )
        return waiting[offset:offset + limit]

    async def audit_document_view(self, actor_id: UUID, actor_role: str, document: Document,
                                  request_id: UUID | None) -> None:
        self.audit_log.append(
            (actor_id, actor_role, SERVICE, DOC_VIEW_ACTION, "KYC_DOCUMENT", document.id,
             None, None, None, None, request_id, None)
        )


_INSERT_TRANSITION = (
    "INSERT INTO kyc.kyc_state_transitions "
    "(submission_id, from_state, to_state, actor_id, reason, at) "
    "VALUES ($1, $2, $3, $4, $5, $6)"
)
_INSERT_AUDIT = (
    "INSERT INTO admin.audit_log (actor_id, actor_role, service, action, target_type, target_id, "
    "before_state, after_state, reason_code, note, request_id, at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12)"
)
_INSERT_DOCUMENT = (
    f"INSERT INTO kyc.kyc_documents ({_DOCUMENT_COLUMNS}) "  # noqa: S608 - constant column list
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
)
_INSERT_AADHAAR = (
    f"INSERT INTO kyc.aadhaar_verifications ({_AADHAAR_COLUMNS}) "  # noqa: S608 - constant
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)"
)
_INSERT_ATTEMPT = (
    f"INSERT INTO kyc.face_match_attempts ({_ATTEMPT_COLUMNS}) "  # noqa: S608 - constant
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
)
_UPDATE_STATE = (
    "UPDATE kyc.kyc_submissions SET state = $1, rejection_reason = $2, decided_at = $3, "
    "decided_by = $4 WHERE id = $5 AND state = $6"
)


def _document_args(document: Document) -> tuple:
    return (
        document.id, document.submission_id, document.doc_type, document.object_key,
        document.mime_type, document.size_bytes, document.sha256, document.uploaded_at,
        document.purge_after,
    )


async def _change_state(connection: Any, transition: Transition, updated: Submission) -> None:
    status = await connection.execute(
        _UPDATE_STATE, updated.state, updated.rejection_reason, updated.decided_at,
        updated.decided_by, updated.id, transition.from_state,
    )
    if status != "UPDATE 1":
        raise StaleSubmission(str(updated.id))
    await connection.execute(
        _INSERT_TRANSITION, transition.submission_id, transition.from_state,
        transition.to_state, transition.actor_id, transition.reason, transition.at,
    )


class PostgresKycRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def latest_for_user(self, user_id: UUID) -> Submission | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_SUBMISSION_COLUMNS} FROM kyc.kyc_submissions "  # noqa: S608 - constant
                "WHERE user_id = $1 ORDER BY submitted_at DESC LIMIT 1",
                user_id,
            )
        return None if row is None else Submission(**dict(row))

    async def get(self, submission_id: UUID) -> Submission | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_SUBMISSION_COLUMNS} FROM kyc.kyc_submissions "  # noqa: S608 - constant
                "WHERE id = $1",
                submission_id,
            )
        return None if row is None else Submission(**dict(row))

    async def documents(self, submission_id: UUID) -> list[Document]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_DOCUMENT_COLUMNS} FROM kyc.kyc_documents "  # noqa: S608 - constant
                "WHERE submission_id = $1 ORDER BY uploaded_at, doc_type",
                submission_id,
            )
        return [Document(**dict(row)) for row in rows]

    async def aadhaar(self, submission_id: UUID) -> AadhaarSummary | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_AADHAAR_COLUMNS} FROM kyc.aadhaar_verifications "  # noqa: S608
                "WHERE submission_id = $1",
                submission_id,
            )
        return None if row is None else _aadhaar_from_row(row)

    async def face_attempts(self, submission_id: UUID) -> list[FaceAttempt]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_ATTEMPT_COLUMNS} FROM kyc.face_match_attempts "  # noqa: S608
                "WHERE submission_id = $1 ORDER BY attempt_no",
                submission_id,
            )
        return [FaceAttempt(**dict(row)) for row in rows]

    async def create(
        self, submission: Submission, documents: list[Document], transition: Transition,
        aadhaar: AadhaarSummary,
    ) -> int:
        import asyncpg

        try:
            async with self.pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    f"INSERT INTO kyc.kyc_submissions ({_SUBMISSION_COLUMNS}) "  # noqa: S608
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    submission.id, submission.user_id, submission.state,
                    submission.rejection_reason, submission.submitted_at, submission.decided_at,
                    submission.decided_by, submission.updated_at,
                )
                await connection.executemany(
                    _INSERT_DOCUMENT, [_document_args(d) for d in documents]
                )
                await connection.execute(_INSERT_AADHAAR, *_aadhaar_args(aadhaar))
                await connection.execute(
                    _INSERT_TRANSITION, transition.submission_id, transition.from_state,
                    transition.to_state, transition.actor_id, transition.reason, transition.at,
                )
                return await mirror_status(
                    connection, submission.user_id, transition.to_state, transition.at
                )
        except asyncpg.UniqueViolationError as exc:
            raise ActiveSubmissionExists(str(submission.user_id)) from exc

    async def record_face_attempt(
        self, attempt: FaceAttempt, documents: list[Document],
        change: tuple[Transition, Submission] | None,
    ) -> int | None:
        import asyncpg

        try:
            async with self.pool.acquire() as connection, connection.transaction():
                await connection.execute(_INSERT_ATTEMPT, *_attempt_args(attempt))
                if documents:
                    await connection.executemany(
                        _INSERT_DOCUMENT, [_document_args(d) for d in documents]
                    )
                if change is None:
                    return None
                transition, updated = change
                await _change_state(connection, transition, updated)
                return await mirror_status(
                    connection, updated.user_id, transition.to_state, transition.at
                )
        except asyncpg.UniqueViolationError as exc:
            raise StaleSubmission(str(attempt.submission_id)) from exc

    async def apply(self, transition: Transition, updated: Submission, actor_role: str,
                    request_id: UUID | None) -> int:
        async with self.pool.acquire() as connection, connection.transaction():
            await _change_state(connection, transition, updated)
            if transition.audit_action:
                await connection.execute(
                    _INSERT_AUDIT, *_audit_row(transition, actor_role, request_id)
                )
            return await mirror_status(
                connection, updated.user_id, transition.to_state, transition.at
            )

    async def queue(self, states: tuple[str, ...], limit: int, offset: int) -> list[Submission]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_SUBMISSION_COLUMNS} FROM kyc.kyc_submissions "  # noqa: S608 - constant
                "WHERE state = ANY($1::text[]) ORDER BY submitted_at, id LIMIT $2 OFFSET $3",
                list(states), limit, offset,
            )
        return [Submission(**dict(row)) for row in rows]

    async def audit_document_view(self, actor_id: UUID, actor_role: str, document: Document,
                                  request_id: UUID | None) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO admin.audit_log (actor_id, actor_role, service, action, "
                "target_type, target_id, request_id) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                actor_id, actor_role, SERVICE, DOC_VIEW_ACTION, "KYC_DOCUMENT", document.id,
                request_id,
            )
