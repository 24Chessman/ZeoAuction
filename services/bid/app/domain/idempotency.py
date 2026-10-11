"""Idempotent bid submission, FR-BID-6 (#31).

``Idempotency-Key`` is claimed with ``SET idem:{key} NX EX 86400`` before anything else on the
hot path. The first request claims the key and runs; a retry finds the stored outcome and
gets it back unchanged (``200`` + ``Idempotent-Replay: true`` for an acceptance, the original
rejection otherwise). The unique ``bids.idempotency_key`` column is the durable backstop
once the Redis entry has expired.

Only definitive outcomes are stored. A transient failure (dependency down, broker
unavailable) releases the key so the client's retry is processed afresh.

Depends only on :class:`KeyValueStore`, which ``redis.asyncio.Redis`` already satisfies.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

PENDING = "PENDING"
DONE = "DONE"
DEFAULT_TTL_SECONDS = 24 * 60 * 60


class KeyValueStore(Protocol):
    async def set(self, name: str, value: str, ex: int | None = None, nx: bool = False) -> Any: ...

    async def get(self, name: str) -> str | None: ...

    async def delete(self, *names: str) -> int: ...


class IdempotencyConflict(Exception):
    """The key cannot be used for this request (in flight, or claimed by another user)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StoredOutcome:
    status_code: int
    body: dict[str, Any]


def redis_key(idempotency_key: str) -> str:
    return f"idem:{idempotency_key}"


class IdempotencyGuard:
    def __init__(self, store: KeyValueStore, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds

    async def claim(self, idempotency_key: str, bidder_id: str) -> StoredOutcome | None:
        """``None`` when this request now owns the key; the stored outcome on a retry."""
        pending = json.dumps({"state": PENDING, "bidder_id": bidder_id})
        for _ in range(2):  # the second pass covers a key expiring between SET and GET
            if await self.store.set(redis_key(idempotency_key), pending, ex=self.ttl_seconds,
                                    nx=True):
                return None
            raw = await self.store.get(redis_key(idempotency_key))
            if raw is None:
                continue
            record = json.loads(raw)
            if record["bidder_id"] != bidder_id:
                # Never reveal another user's outcome; keys are global, like the DB column.
                raise IdempotencyConflict("Idempotency-Key was already used by another request")
            if record["state"] == PENDING:
                raise IdempotencyConflict("A request with this Idempotency-Key is in progress")
            return StoredOutcome(status_code=record["status_code"], body=record["body"])
        raise IdempotencyConflict("Idempotency-Key could not be claimed; retry")

    async def complete(
        self, idempotency_key: str, bidder_id: str, status_code: int, body: dict[str, Any]
    ) -> None:
        record = {"state": DONE, "bidder_id": bidder_id, "status_code": status_code, "body": body}
        await self.store.set(redis_key(idempotency_key), json.dumps(record), ex=self.ttl_seconds)

    async def release(self, idempotency_key: str) -> None:
        await self.store.delete(redis_key(idempotency_key))
