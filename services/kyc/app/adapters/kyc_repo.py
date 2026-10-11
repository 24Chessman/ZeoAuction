"""KYC persistence (role ``kyc_svc``): PostgreSQL for real, in-memory for tests.

Each accepted transition is one transaction (services/kyc/docs/design.md section 2):
1. ``UPDATE kyc_submissions ... WHERE id = $1 AND state = $from``; 0 rows means another
   admin won the race (:class:`StaleSubmission`);
2. a row in the append-only ``kyc_state_transitions``;
3. the ``auth.users`` mirror with a ``token_version`` bump;
4. an ``admin.audit_log`` row for administrator actions.
"""

import json
from typing import Any, Protocol
from uuid import UUID

from app.adapters.user_mirror import InMemoryUserMirror, mirror_status
from app.domain.submission import Document, Submission
from app.domain.verification import DOC_VIEW_ACTION, Transition

SERVICE = "kyc"
_SUBMISSION_COLUMNS = (
    "id, user_id, state, rejection_reason, submitted_at, decided_at, decided_by, updated_at"
)
_DOCUMENT_COLUMNS = (
    "id, submission_id, doc_type, object_key, mime_type, size_bytes, sha256, uploaded_at, "
    "purge_after"
)


class StaleSubmission(Exception):
    """The row was not in the expected state any more; re-read and re-evaluate."""


class ActiveSubmissionExists(Exception):
    """The user already has a live (non-rejected) submission."""


class DocumentTypeExists(Exception):
    pass


class KycRepository(Protocol):
    async def latest_for_user(self, user_id: UUID) -> Submission | None: ...

    async def get(self, submission_id: UUID) -> Submission | None: ...

    async def documents(self, submission_id: UUID) -> list[Document]: ...

    async def create(
        self, submission: Submission, documents: list[Document], transition: Transition
    ) -> int: ...

    async def add_document(self, document: Document) -> None: ...

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


class InMemoryKycRepository:
    def __init__(self, mirror: InMemoryUserMirror | None = None) -> None:
        self.submissions: dict[UUID, Submission] = {}
        self.docs: dict[UUID, Document] = {}
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

    async def create(
        self, submission: Submission, documents: list[Document], transition: Transition
    ) -> int:
        if any(s.user_id == submission.user_id and s.state != "REJECTED"
               for s in self.submissions.values()):
            raise ActiveSubmissionExists(str(submission.user_id))
        self.submissions[submission.id] = submission
        for document in documents:
            self.docs[document.id] = document
        self.transitions.append(transition)
        return self.mirror.mirror(submission.user_id, transition.to_state)

    async def add_document(self, document: Document) -> None:
        if any(d.submission_id == document.submission_id and d.doc_type == document.doc_type
               for d in self.docs.values()):
            raise DocumentTypeExists(document.doc_type)
        self.docs[document.id] = document

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
    "INSERT INTO kyc_state_transitions (submission_id, from_state, to_state, actor_id, reason, at) "
    "VALUES ($1, $2, $3, $4, $5, $6)"
)
_INSERT_AUDIT = (
    "INSERT INTO admin.audit_log (actor_id, actor_role, service, action, target_type, target_id, "
    "before_state, after_state, reason_code, note, request_id, at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12)"
)
_INSERT_DOCUMENT = (
    f"INSERT INTO kyc_documents ({_DOCUMENT_COLUMNS}) "  # noqa: S608 - constant column list
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
)


def _document_args(document: Document) -> tuple:
    return (
        document.id, document.submission_id, document.doc_type, document.object_key,
        document.mime_type, document.size_bytes, document.sha256, document.uploaded_at,
        document.purge_after,
    )


class PostgresKycRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def latest_for_user(self, user_id: UUID) -> Submission | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_SUBMISSION_COLUMNS} FROM kyc_submissions "  # noqa: S608 - constant
                "WHERE user_id = $1 ORDER BY submitted_at DESC LIMIT 1",
                user_id,
            )
        return None if row is None else Submission(**dict(row))

    async def get(self, submission_id: UUID) -> Submission | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_SUBMISSION_COLUMNS} FROM kyc_submissions "  # noqa: S608 - constant
                "WHERE id = $1",
                submission_id,
            )
        return None if row is None else Submission(**dict(row))

    async def documents(self, submission_id: UUID) -> list[Document]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_DOCUMENT_COLUMNS} FROM kyc_documents "  # noqa: S608 - constant
                "WHERE submission_id = $1 ORDER BY uploaded_at, doc_type",
                submission_id,
            )
        return [Document(**dict(row)) for row in rows]

    async def create(
        self, submission: Submission, documents: list[Document], transition: Transition
    ) -> int:
        import asyncpg

        try:
            async with self.pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    f"INSERT INTO kyc_submissions ({_SUBMISSION_COLUMNS}) "  # noqa: S608
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    submission.id, submission.user_id, submission.state,
                    submission.rejection_reason, submission.submitted_at, submission.decided_at,
                    submission.decided_by, submission.updated_at,
                )
                await connection.executemany(
                    _INSERT_DOCUMENT, [_document_args(d) for d in documents]
                )
                await connection.execute(
                    _INSERT_TRANSITION, transition.submission_id, transition.from_state,
                    transition.to_state, transition.actor_id, transition.reason, transition.at,
                )
                return await mirror_status(
                    connection, submission.user_id, transition.to_state, transition.at
                )
        except asyncpg.UniqueViolationError as exc:
            raise ActiveSubmissionExists(str(submission.user_id)) from exc

    async def add_document(self, document: Document) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            exists = await connection.fetchval(
                "SELECT 1 FROM kyc_documents WHERE submission_id = $1 AND doc_type = $2",
                document.submission_id, document.doc_type,
            )
            if exists:
                raise DocumentTypeExists(document.doc_type)
            await connection.execute(_INSERT_DOCUMENT, *_document_args(document))

    async def apply(self, transition: Transition, updated: Submission, actor_role: str,
                    request_id: UUID | None) -> int:
        async with self.pool.acquire() as connection, connection.transaction():
            status = await connection.execute(
                "UPDATE kyc_submissions SET state = $1, rejection_reason = $2, decided_at = $3, "
                "decided_by = $4 WHERE id = $5 AND state = $6",
                updated.state, updated.rejection_reason, updated.decided_at, updated.decided_by,
                updated.id, transition.from_state,
            )
            if status != "UPDATE 1":
                raise StaleSubmission(str(updated.id))
            await connection.execute(
                _INSERT_TRANSITION, transition.submission_id, transition.from_state,
                transition.to_state, transition.actor_id, transition.reason, transition.at,
            )
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
                f"SELECT {_SUBMISSION_COLUMNS} FROM kyc_submissions "  # noqa: S608 - constant
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
