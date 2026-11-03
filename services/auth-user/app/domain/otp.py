"""One-time password (OTP) domain logic for Gmail/email verification."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class OtpRecord:
    email: str
    code: str
    created_at: datetime
    expires_at: datetime
    consumed: bool = False


class OtpStore:
    """In-memory OTP store for testing and fallback."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._otps: dict[str, OtpRecord] = {}

    def issue(self, email: str) -> OtpRecord:
        now = datetime.now(UTC)
        code = f"{secrets.randbelow(1_000_000):06d}"
        record = OtpRecord(
            email=email.strip().lower(),
            code=code,
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            consumed=False,
        )
        self._otps[record.email] = record
        return record

    def verify(self, email: str, code: str) -> bool:
        normalized = email.strip().lower()
        record = self._otps.get(normalized)
        if not record:
            return False
        now = datetime.now(UTC)
        if record.consumed or record.expires_at < now:
            return False
        if not secrets.compare_digest(record.code, code.strip()):
            return False
        # Mark consumed
        self._otps[normalized] = OtpRecord(
            email=record.email,
            code=record.code,
            created_at=record.created_at,
            expires_at=record.expires_at,
            consumed=True,
        )
        return True
