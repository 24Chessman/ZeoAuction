import dataclasses
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest

from zeo_common.audit import (
    INSERT_AUDIT,
    AuditEntry,
    AuditError,
    InMemoryAuditWriter,
    PostgresAuditWriter,
    audit_args,
    snapshot,
    write_audit,
)

ADMIN = UUID("00000000-0000-4000-8000-0000000000a1")
DISPUTE = UUID("00000000-0000-4000-8000-0000000000d1")
AT = datetime(2026, 10, 1, 12, tzinfo=UTC)


class State(Enum):
    RESOLVED_BUYER = "RESOLVED_BUYER"


def entry(**overrides) -> AuditEntry:
    fields = dict(actor_id=ADMIN, actor_role="ADMIN", service="dispute",
                  action="DISPUTE_RESOLVE", target_type="DISPUTE", target_id=DISPUTE,
                  before_state={"state": "UNDER_REVIEW"},
                  after_state={"state": State.RESOLVED_BUYER, "refund": Decimal("1349"),
                               "resolved_at": AT, "order_id": DISPUTE},
                  reason_code="SELLER", note="item never shipped", at=AT)
    return AuditEntry(**(fields | overrides))


class FakeConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


class FakePool(FakeConnection):
    @asynccontextmanager
    async def acquire(self):
        yield self


def test_snapshots_keep_money_as_strings_and_times_as_utc():
    after = json.loads(audit_args(entry())[7])
    assert after == {"state": "RESOLVED_BUYER", "refund": "1349.00",
                     "resolved_at": "2026-10-01T12:00:00Z", "order_id": str(DISPUTE)}


def test_snapshots_refuse_floats_anywhere():
    for bad in ({"refund": 13.49}, {"rows": [{"amount": 1.0}]}, {"pair": (1, 2.5)}):
        with pytest.raises(AuditError):
            snapshot(bad)


def test_snapshots_refuse_naive_times_and_unknown_types():
    with pytest.raises(AuditError):
        snapshot({"at": datetime(2026, 10, 1)})
    with pytest.raises(TypeError):
        snapshot({"blob": object()})
    assert snapshot(None) is None


@pytest.mark.parametrize("overrides", [
    {"actor_role": "SUPERUSER"},
    {"action": "resolve"},
    {"action": "X"},
    {"service": ""},
    {"target_type": ""},
    {"at": datetime(2026, 10, 1)},
    {"at": datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))},
])
def test_invalid_entries_are_refused(overrides):
    with pytest.raises(AuditError):
        entry(**overrides)


def test_entries_cannot_be_changed_once_made():
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry().note = "edited"


def test_default_timestamp_is_utc_now():
    made = AuditEntry(actor_id=ADMIN, actor_role="SYSTEM", service="kyc",
                      action="KYC_DOC_VIEW", target_type="KYC_DOCUMENT", target_id=DISPUTE)
    assert made.at.tzinfo is UTC
    assert abs(made.at - datetime.now(UTC)) < timedelta(seconds=5)


async def test_write_audit_uses_the_callers_connection():
    conn = FakeConnection()
    await write_audit(conn, entry())
    (sql, args), = conn.calls
    assert sql == INSERT_AUDIT and sql.startswith("INSERT INTO admin.audit_log")
    assert "UPDATE" not in sql and "DELETE" not in sql
    assert args[:6] == (ADMIN, "ADMIN", "dispute", "DISPUTE_RESOLVE", "DISPUTE", DISPUTE)
    assert args[-1] == AT and len(args) == 12


async def test_postgres_writer_acquires_a_connection():
    pool = FakePool()
    await PostgresAuditWriter(pool).write(entry())
    assert pool.calls[0][0] == INSERT_AUDIT


async def test_in_memory_writer_validates_and_filters():
    writer = InMemoryAuditWriter()
    await writer.write(entry())
    await writer.write(entry(target_id=ADMIN, target_type="USER", action="USER_SUSPEND"))
    assert len(writer.entries) == 2
    assert [e.action for e in writer.for_target("DISPUTE", DISPUTE)] == ["DISPUTE_RESOLVE"]
    with pytest.raises(AuditError):
        await writer.write(entry(after_state={"refund": 1.5}))
    assert len(writer.entries) == 2
