"""Rotating refresh tokens with reuse detection (FR-AUTH-2, #91, SDD 9.1).

Every refresh token is single-use. Using one rotates it: the old row is marked rotated and
points at its replacement, which joins the same *family*. Presenting a token that was
already rotated (or revoked) means a copy is in someone else's hands, so the **whole family
is revoked**: the attacker's and the victim's sessions both end, and the victim logs in
again. Logout revokes the family too.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.security.tokens import hash_refresh_token, new_refresh_token

DEFAULT_TTL = timedelta(days=14)


@dataclass(frozen=True)
class RefreshRecord:
    id: UUID
    user_id: UUID
    family_id: UUID
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by: UUID | None = None


class RefreshTokenStore(Protocol):
    async def add(self, record: RefreshRecord) -> None: ...

    async def get_by_hash(self, token_hash: str) -> RefreshRecord | None: ...

    async def rotate(self, old: RefreshRecord, new: RefreshRecord, at: datetime) -> bool:
        """Atomically store ``new`` and mark ``old`` rotated, only if ``old`` is still live."""
        ...

    async def revoke_family(self, family_id: UUID, at: datetime) -> None: ...


class RefreshTokenError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def invalid() -> RefreshTokenError:
    return RefreshTokenError("REFRESH_TOKEN_INVALID", "Refresh token is invalid or expired")


def reused() -> RefreshTokenError:
    return RefreshTokenError(
        "REFRESH_TOKEN_REUSED", "Refresh token was already used; all sessions were signed out"
    )


class RefreshTokens:
    def __init__(
        self,
        store: RefreshTokenStore,
        ttl: timedelta = DEFAULT_TTL,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.ttl = ttl
        self.clock = clock

    def _new(self, user_id: UUID, family_id: UUID) -> tuple[str, RefreshRecord]:
        token = new_refresh_token()
        now = self.clock()
        record = RefreshRecord(
            id=uuid4(), user_id=user_id, family_id=family_id,
            token_hash=hash_refresh_token(token), issued_at=now, expires_at=now + self.ttl,
        )
        return token, record

    async def issue(self, user_id: UUID) -> str:
        """Start a new family (a login)."""
        token, record = self._new(user_id, uuid4())
        await self.store.add(record)
        return token

    async def rotate(self, token: str) -> tuple[UUID, str]:
        """Exchange ``token`` for a new one. Returns ``(user_id, new_token)``."""
        record = await self.store.get_by_hash(hash_refresh_token(token))
        now = self.clock()
        if record is None:
            raise invalid()
        if record.rotated_at is not None or record.revoked_at is not None:
            await self.store.revoke_family(record.family_id, now)
            raise reused()
        if record.expires_at <= now:
            raise invalid()
        new_token, new_record = self._new(record.user_id, record.family_id)
        if not await self.store.rotate(record, new_record, now):
            # Lost a race with another use of the same token: that is reuse too.
            await self.store.revoke_family(record.family_id, now)
            raise reused()
        return record.user_id, new_token

    async def revoke(self, token: str) -> None:
        record = await self.store.get_by_hash(hash_refresh_token(token))
        if record is not None:
            await self.store.revoke_family(record.family_id, self.clock())


class InMemoryRefreshTokenStore:
    def __init__(self) -> None:
        self.records: dict[UUID, RefreshRecord] = {}

    async def add(self, record: RefreshRecord) -> None:
        self.records[record.id] = record

    async def get_by_hash(self, token_hash: str) -> RefreshRecord | None:
        return next((r for r in self.records.values() if r.token_hash == token_hash), None)

    async def rotate(self, old: RefreshRecord, new: RefreshRecord, at: datetime) -> bool:
        current = self.records[old.id]
        if current.rotated_at is not None or current.revoked_at is not None:
            return False
        self.records[new.id] = new
        self.records[old.id] = replace(current, rotated_at=at, replaced_by=new.id)
        return True

    async def revoke_family(self, family_id: UUID, at: datetime) -> None:
        for record_id, record in list(self.records.items()):
            if record.family_id == family_id and record.revoked_at is None:
                self.records[record_id] = replace(record, revoked_at=at)
