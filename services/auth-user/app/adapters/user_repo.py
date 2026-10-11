"""Persistence for ``auth.users`` and ``auth.refresh_tokens`` (role ``auth_svc``)."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.refresh_tokens import RefreshRecord
from app.domain.users import User, normalise_email

_USER_COLUMNS = (
    "id, email::text AS email, password_hash, display_name, role, kyc_status, suspended, "
    "token_version, created_at, updated_at"
)
_REFRESH_COLUMNS = (
    "id, user_id, family_id, token_hash, issued_at, expires_at, rotated_at, revoked_at, "
    "replaced_by"
)


class EmailTaken(Exception):
    pass


class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def update_display_name(self, user_id: UUID, display_name: str) -> User | None: ...

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None: ...


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}

    async def add(self, user: User) -> None:
        if await self.get_by_email(user.email):
            raise EmailTaken(user.email)
        self.users[user.id] = user

    async def get(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        wanted = normalise_email(email)
        return next((u for u in self.users.values() if u.email.lower() == wanted), None)

    async def update_display_name(self, user_id: UUID, display_name: str) -> User | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        user = replace(user, display_name=display_name, updated_at=datetime.now(UTC))
        self.users[user_id] = user
        return user

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        self.users[user_id] = replace(self.users[user_id], password_hash=password_hash)


class PostgresUserRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def add(self, user: User) -> None:
        import asyncpg

        try:
            async with self.pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO users (id, email, password_hash, display_name) "
                    "VALUES ($1, $2, $3, $4)",
                    user.id, user.email, user.password_hash, user.display_name,
                )
        except asyncpg.UniqueViolationError as exc:
            raise EmailTaken(user.email) from exc

    async def _one(self, where: str, value: Any) -> User | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_USER_COLUMNS} FROM users WHERE {where} = $1",  # noqa: S608 - constant
                value,
            )
        return None if row is None else User(**dict(row))

    async def get(self, user_id: UUID) -> User | None:
        return await self._one("id", user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self._one("email", normalise_email(email))

    async def update_display_name(self, user_id: UUID, display_name: str) -> User | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"UPDATE users SET display_name = $1 WHERE id = $2 "  # noqa: S608 - constant
                f"RETURNING {_USER_COLUMNS}",
                display_name, user_id,
            )
        return None if row is None else User(**dict(row))

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE users SET password_hash = $1 WHERE id = $2", password_hash, user_id
            )


class PostgresRefreshTokenStore:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def add(self, record: RefreshRecord) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, issued_at, "
                "expires_at) VALUES ($1, $2, $3, $4, $5, $6)",
                record.id, record.user_id, record.family_id, record.token_hash,
                record.issued_at, record.expires_at,
            )

    async def get_by_hash(self, token_hash: str) -> RefreshRecord | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_REFRESH_COLUMNS} FROM refresh_tokens "  # noqa: S608 - constant
                "WHERE token_hash = $1",
                token_hash,
            )
        return None if row is None else RefreshRecord(**dict(row))

    async def rotate(self, old: RefreshRecord, new: RefreshRecord, at: datetime) -> bool:
        try:
            async with self.pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, issued_at, "
                    "expires_at) VALUES ($1, $2, $3, $4, $5, $6)",
                    new.id, new.user_id, new.family_id, new.token_hash, new.issued_at,
                    new.expires_at,
                )
                status = await connection.execute(
                    "UPDATE refresh_tokens SET rotated_at = $1, replaced_by = $2 "
                    "WHERE id = $3 AND rotated_at IS NULL AND revoked_at IS NULL",
                    at, new.id, old.id,
                )
                if status != "UPDATE 1":
                    raise _LostRace
        except _LostRace:
            return False
        return True

    async def revoke_family(self, family_id: UUID, at: datetime) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE refresh_tokens SET revoked_at = $1 "
                "WHERE family_id = $2 AND revoked_at IS NULL",
                at, family_id,
            )


class _LostRace(Exception):
    """Raised inside the transaction so the new row is rolled back."""
