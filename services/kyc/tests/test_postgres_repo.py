"""The PostgreSQL repository's statements, against a recording fake of asyncpg.

The real schema and grants are proven by ``make verify-db`` on the Compose stack; this checks
the order of writes inside each transaction and the optimistic state check.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.adapters.kyc_repo import (
    ActiveSubmissionExists,
    DocumentTypeExists,
    PostgresKycRepository,
    StaleSubmission,
)
from app.adapters.user_mirror import UnknownUser
from app.domain.submission import Submission, new_document, validate_upload
from app.domain.verification import plan_transition, submit_transition
from tests.support import PDF

NOW = datetime(2026, 9, 10, tzinfo=UTC)


class FakeConnection:
    def __init__(self, pool):
        self.pool = pool

    @asynccontextmanager
    async def transaction(self):
        self.pool.log.append(("BEGIN",))
        try:
            yield
        except BaseException:
            self.pool.log.append(("ROLLBACK",))
            raise
        self.pool.log.append(("COMMIT",))

    async def execute(self, sql, *args):
        self.pool.log.append((sql, args))
        if self.pool.raise_on and self.pool.raise_on in sql:
            raise self.pool.error
        return self.pool.status.get(sql.split()[0], "INSERT 0 1")

    async def executemany(self, sql, rows):
        self.pool.log.append((sql, tuple(rows)))

    async def fetchval(self, sql, *args):
        self.pool.log.append((sql, args))
        return self.pool.values.pop(0) if self.pool.values else None

    async def fetchrow(self, sql, *args):
        self.pool.log.append((sql, args))
        return self.pool.rows.pop(0) if self.pool.rows else None

    async def fetch(self, sql, *args):
        self.pool.log.append((sql, args))
        return self.pool.rows


class FakePool:
    def __init__(self):
        self.log = []
        self.values = []
        self.rows = []
        self.status = {}
        self.raise_on = None
        self.error = None

    @asynccontextmanager
    async def acquire(self):
        yield FakeConnection(self)

    def statements(self):
        return [entry[0].split(" (")[0] if len(entry) > 1 else entry[0] for entry in self.log]


def submission(state="SUBMITTED") -> Submission:
    return Submission(id=uuid4(), user_id=uuid4(), state=state, rejection_reason=None,
                      submitted_at=NOW, decided_at=None, decided_by=None, updated_at=NOW)


def document_for(row: Submission):
    return new_document(validate_upload("GOVERNMENT_ID", PDF, None), doc_id=uuid4(),
                        submission=row, now=NOW, retention_days=30)


async def test_create_writes_row_documents_transition_and_mirror_in_one_transaction():
    pool = FakePool()
    pool.values = [2]
    row = submission()
    version = await PostgresKycRepository(pool).create(
        row, [document_for(row)], submit_transition(row, NOW, None)
    )
    assert version == 2
    assert pool.statements() == [
        "BEGIN",
        "INSERT INTO kyc_submissions",
        "INSERT INTO kyc_documents",
        "INSERT INTO kyc_state_transitions",
        "UPDATE auth.users SET kyc_status = $1, kyc_status_updated_at = $2, token_version = "
        "token_version + 1 WHERE id = $3 RETURNING token_version",
        "COMMIT",
    ]


async def test_create_maps_the_one_live_submission_index_to_a_domain_error():
    import asyncpg

    pool = FakePool()
    pool.raise_on = "INSERT INTO kyc_submissions"
    pool.error = asyncpg.UniqueViolationError("kyc_submissions_one_live_per_user")
    row = submission()
    with pytest.raises(ActiveSubmissionExists):
        await PostgresKycRepository(pool).create(row, [], submit_transition(row, NOW, None))
    assert pool.log[-1] == ("ROLLBACK",)


async def test_create_rolls_back_when_the_user_is_unknown():
    pool = FakePool()
    row = submission()
    with pytest.raises(UnknownUser):
        await PostgresKycRepository(pool).create(row, [], submit_transition(row, NOW, None))
    assert pool.log[-1] == ("ROLLBACK",)


async def test_admin_transition_updates_with_a_state_check_and_audits():
    pool = FakePool()
    pool.status = {"UPDATE": "UPDATE 1"}
    pool.values = [3]
    row = submission("UNDER_REVIEW")
    transition, updated = plan_transition(row, "approve", actor_id=uuid4(), reason=None, now=NOW)
    assert await PostgresKycRepository(pool).apply(transition, updated, "ADMIN", None) == 3
    update = pool.log[1]
    assert update[0].endswith("WHERE id = $5 AND state = $6")
    assert update[1][-1] == "UNDER_REVIEW"
    statements = pool.statements()
    assert statements[2] == "INSERT INTO kyc_state_transitions"
    assert statements[3] == "INSERT INTO admin.audit_log"
    assert statements[-1] == "COMMIT"


async def test_a_lost_race_rolls_back_without_writing_anything_else():
    pool = FakePool()
    pool.status = {"UPDATE": "UPDATE 0"}
    row = submission()
    transition, updated = plan_transition(row, "startReview", actor_id=uuid4(), reason=None,
                                          now=NOW)
    with pytest.raises(StaleSubmission):
        await PostgresKycRepository(pool).apply(transition, updated, "ADMIN", None)
    assert pool.statements()[-1] == "ROLLBACK"
    assert "INSERT INTO kyc_state_transitions" not in pool.statements()


async def test_reads():
    pool = FakePool()
    row = submission()
    pool.rows = [dict(row.__dict__)]
    repo = PostgresKycRepository(pool)
    assert await repo.latest_for_user(row.user_id) == row
    assert await repo.get(row.id) is None
    pool.rows = [dict(row.__dict__)]
    assert await repo.queue(("SUBMITTED",), 10, 0) == [row]
    doc = document_for(row)
    pool.rows = [dict(doc.__dict__)]
    assert await repo.documents(row.id) == [doc]


async def test_add_document_refuses_a_duplicate_type():
    pool = FakePool()
    row = submission()
    repo = PostgresKycRepository(pool)
    await repo.add_document(document_for(row))
    assert pool.statements()[-2] == "INSERT INTO kyc_documents"
    pool.values = [1]
    with pytest.raises(DocumentTypeExists):
        await repo.add_document(document_for(row))


async def test_document_views_are_audited():
    pool = FakePool()
    row = submission()
    await PostgresKycRepository(pool).audit_document_view(uuid4(), "ADMIN", document_for(row),
                                                          None)
    sql, args = pool.log[0]
    assert sql.startswith("INSERT INTO admin.audit_log")
    assert args[3] == "KYC_DOC_VIEW"
