"""Test support for Admin & Moderation service."""

from datetime import UTC, datetime
from uuid import UUID

from app.settings import Settings
from zeo_common.auth import JwtSettings, encode_access_token

JWT = JwtSettings(secret="admin-test-secret-32-bytes-long!!")
ADMIN = UUID("00000000-0000-4000-8000-000000000001")
USER1 = UUID("00000000-0000-4000-8000-000000000002")
USER2 = UUID("00000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

SETTINGS = Settings(
    database_url="unused",
    repository="memory",
    redis_url="unused",
)


def bearer(user_id: UUID = ADMIN, *, role: str = "ADMIN") -> dict[str, str]:
    token = encode_access_token(
        JWT,
        user_id=user_id,
        role=role,
        kyc_status="VERIFIED",
        suspended=False,
    )
    return {"Authorization": f"Bearer {token}"}
