"""Append-only audit-log writer for ``admin.audit_log`` (FR-ADMIN-3, SDD 8.8). Owner: Jay (#83).

Every administrative action, in whichever service performs it (KYC, Dispute, Payment, Admin),
writes one row. The table has no UPDATE/DELETE grant and a trigger that stops even its owner
(``infra/postgres/init/85-admin.sql``); the services other than Admin may only INSERT
(documented exception, ``docs/architecture.md``). A correction is a new row, never an edit.

Write the row **in the same transaction as the action** it records, so an action is never
committed without its audit row, nor the reverse::

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE ...")                     # the action
        await write_audit(conn, AuditEntry(...))             # its audit row

The table lives in another schema than most callers' ``search_path``, so the statement names
``admin.audit_log`` explicitly. ``before_state``/``after_state`` are JSON snapshots: money stays
a two-decimal string (pass strings, or ``Decimal``, which is rendered with
:func:`zeo_common.format_money`), timestamps are ISO-8601 UTC.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from zeo_common.money import format_money

ACTION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
ACTOR_ROLES = frozenset({"ADMIN", "USER", "SYSTEM"})

INSERT_AUDIT = (
    "INSERT INTO admin.audit_log (actor_id, actor_role, service, action, target_type, "
    "target_id, before_state, after_state, reason_code, note, request_id, at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12)"
)


class AuditError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AuditEntry:
    actor_id: UUID
    actor_role: str
    service: str
    action: str  # e.g. KYC_APPROVE, USER_SUSPEND, DISPUTE_RESOLVE, KYC_DOC_VIEW
    target_type: str
    target_id: UUID
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    reason_code: str | None = None
    note: str | None = None
    request_id: UUID | None = None
    at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.actor_role not in ACTOR_ROLES:
            raise AuditError(f"actor_role must be one of {sorted(ACTOR_ROLES)}")
        if not ACTION_PATTERN.match(self.action):
            raise AuditError(f"action must be UPPER_SNAKE_CASE, got {self.action!r}")
        if not self.service or not self.target_type:
            raise AuditError("service and target_type are required")
        if self.at.tzinfo is None or self.at.utcoffset() != UTC.utcoffset(None):
            raise AuditError("at must be a timezone-aware UTC timestamp")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format_money(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise AuditError("timestamps in audit snapshots must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):  # pragma: no cover - json handles floats before default
        raise AuditError("floats are not allowed in audit snapshots")
    raise TypeError(f"cannot record {type(value).__name__} in an audit snapshot")


def snapshot(state: dict[str, Any] | None) -> str | None:
    """Serialise a before/after snapshot; refuses floats so money can't drift."""
    if state is None:
        return None
    _refuse_floats(state)
    return json.dumps(state, default=_json_default, sort_keys=True, separators=(",", ":"))


def _refuse_floats(value: Any) -> None:
    if isinstance(value, float):
        raise AuditError("floats are not allowed in audit snapshots; use Decimal or strings")
    if isinstance(value, dict):
        for item in value.values():
            _refuse_floats(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _refuse_floats(item)


def audit_args(entry: AuditEntry) -> tuple[Any, ...]:
    """Positional arguments for :data:`INSERT_AUDIT`."""
    return (
        entry.actor_id, entry.actor_role, entry.service, entry.action, entry.target_type,
        entry.target_id, snapshot(entry.before_state), snapshot(entry.after_state),
        entry.reason_code, entry.note, entry.request_id, entry.at,
    )


class Executor(Protocol):
    async def execute(self, query: str, *args: Any) -> Any: ...


async def write_audit(connection: Executor, entry: AuditEntry) -> None:
    """Append one row using the caller's connection (and so its transaction)."""
    await connection.execute(INSERT_AUDIT, *audit_args(entry))


class AuditWriter(Protocol):
    async def write(self, entry: AuditEntry) -> None: ...


class PostgresAuditWriter:
    """For an audited action that has no transaction of its own (e.g. viewing a document)."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def write(self, entry: AuditEntry) -> None:
        async with self.pool.acquire() as connection:
            await write_audit(connection, entry)


class InMemoryAuditWriter:
    """Test and memory-mode stand-in. Entries are frozen; there is no way to change one."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def write(self, entry: AuditEntry) -> None:
        audit_args(entry)  # same validation as the database path
        self._entries.append(entry)

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def for_target(self, target_type: str, target_id: UUID) -> list[AuditEntry]:
        return [e for e in self._entries
                if e.target_type == target_type and e.target_id == target_id]
