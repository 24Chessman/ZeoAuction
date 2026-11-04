"""Email token generation and validation for email verification and password reset."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID


@dataclass(frozen=True)
class EmailTokenRecord:
    id: UUID
    user_id: UUID
    token_hash: str
    token_type: str  # 'VERIFY_EMAIL' or 'RESET_PASSWORD'
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


def generate_raw_token() -> str:
    """Generate a high-entropy URL-safe token."""
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """Hash the raw token with SHA-256 for persistent storage."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


class InMemoryEmailTokenStore:
    def __init__(self) -> None:
        self._tokens: dict[str, EmailTokenRecord] = {}

    def issue(
        self, user_id: UUID, token_type: str, ttl_hours: int = 24
    ) -> tuple[str, EmailTokenRecord]:
        raw_token = generate_raw_token()
        token_hash = hash_token(raw_token)
        now = datetime.now(UTC)
        record = EmailTokenRecord(
            id=secrets.token_bytes(16),  # or uuid4()
            user_id=user_id,
            token_hash=token_hash,
            token_type=token_type,
            created_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
            consumed_at=None,
        )
        self._tokens[token_hash] = record
        return raw_token, record

    def get_valid(self, raw_token: str, token_type: str) -> EmailTokenRecord | None:
        token_hash = hash_token(raw_token)
        record = self._tokens.get(token_hash)
        if not record or record.token_type != token_type:
            return None
        now = datetime.now(UTC)
        if record.consumed_at is not None or record.expires_at < now:
            return None
        return record

    def get_record(self, raw_token: str, token_type: str) -> EmailTokenRecord | None:
        """Retrieve token record regardless of consumed status (for idempotent checks)."""
        token_hash = hash_token(raw_token)
        record = self._tokens.get(token_hash)
        if not record or record.token_type != token_type:
            return None
        return record

    def consume(self, raw_token: str) -> bool:
        token_hash = hash_token(raw_token)
        record = self._tokens.get(token_hash)
        if not record:
            return False
        self._tokens[token_hash] = EmailTokenRecord(
            id=record.id,
            user_id=record.user_id,
            token_hash=record.token_hash,
            token_type=record.token_type,
            created_at=record.created_at,
            expires_at=record.expires_at,
            consumed_at=datetime.now(UTC),
        )
        return True
