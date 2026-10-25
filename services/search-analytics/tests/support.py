"""Test support for Search & Analytics service."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.adapters.order_client import InMemoryOrderClient
from app.adapters.search_repo import InMemorySearchRepository
from app.domain.models import IndexedAuction
from app.main import build_app
from app.settings import Settings
from fastapi.testclient import TestClient
from zeo_common.auth import JwtSettings, encode_access_token

JWT = JwtSettings(secret="search-test-secret-32-bytes-long!!")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
BUYER = UUID("00000000-0000-4000-8000-000000000003")
OTHER = UUID("00000000-0000-4000-8000-000000000009")
ADMIN = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

SETTINGS = Settings(
    database_url="unused",
    repository="memory",
    payment_service_url="http://unused",
    internal_service_token="test-internal-token",
)

INTERNAL = {"X-Internal-Token": "test-internal-token"}


def bearer(user_id: UUID = BUYER, *, role: str = "USER") -> dict[str, str]:
    token = encode_access_token(
        JWT,
        user_id=user_id,
        role=role,
        kyc_status="VERIFIED",
        suspended=False,
    )
    return {"Authorization": f"Bearer {token}"}


def make_auction(
    *,
    auction_id: UUID | None = None,
    seller_id: UUID = SELLER,
    title: str = "Test Auction",
    description: str = "A test auction item",
    category: str = "Electronics",
    current_price: str = "1000.00",
    currency: str = "INR",
    state: str = "ACTIVE",
    closes_at: datetime | None = None,
    created_at: datetime | None = None,
) -> IndexedAuction:
    from uuid import uuid4

    return IndexedAuction(
        auction_id=auction_id or uuid4(),
        seller_id=seller_id,
        title=title,
        description=description,
        category=category,
        current_price=Decimal(current_price),
        currency=currency,
        state=state,
        closes_at=closes_at or NOW,
        created_at=created_at or NOW,
        updated_at=NOW,
    )


def build_test_app(
    repo: InMemorySearchRepository | None = None,
    order_client: InMemoryOrderClient | None = None,
) -> TestClient:
    app = build_app(
        SETTINGS,
        repo or InMemorySearchRepository(),
        order_client or InMemoryOrderClient(),
        jwt_settings=JWT,
        clock=lambda: NOW,
    )
    return TestClient(app)
