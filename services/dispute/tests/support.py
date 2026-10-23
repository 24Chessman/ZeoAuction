"""Test support for Dispute service."""

from datetime import UTC, datetime
from uuid import UUID

from app.adapters.payment_client import InMemoryPaymentClient, OrderInfo
from app.settings import Settings
from zeo_common.auth import JwtSettings, encode_access_token

JWT = JwtSettings(secret="dispute-test-secret-32-bytes-long!!")
BUYER = UUID("00000000-0000-4000-8000-000000000003")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
ADMIN = UUID("00000000-0000-4000-8000-000000000001")
OTHER_USER = UUID("00000000-0000-4000-8000-000000000009")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

SETTINGS = Settings(
    database_url="unused",
    repository="memory",
    payment_service_url="http://unused",
    internal_token="test-internal-token",
)


def bearer(user_id: UUID = BUYER, *, role: str = "USER") -> dict[str, str]:
    token = encode_access_token(
        JWT,
        user_id=user_id,
        role=role,
        kyc_status="VERIFIED",
        suspended=False,
    )
    return {"Authorization": f"Bearer {token}"}
