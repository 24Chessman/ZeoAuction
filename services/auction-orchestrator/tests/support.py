from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.adapters.auction_repo import InMemoryAuctionRepository
from app.adapters.kafka_producer import InMemoryAuctionEventPublisher
from app.domain.auction import Auction, new_draft
from app.main import build_app
from app.settings import Settings
from zeo_common.auth import JwtSettings, encode_access_token
from zeo_common.gateway import InMemoryTokenVersions

JWT = JwtSettings(secret="orchestrator-test-secret-32-bytes!!")
SETTINGS = Settings(database_url="unused", repository="memory", redis_url="unused",
                    kafka_bootstrap_servers="unused")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
ADMIN = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def bearer(user_id: UUID = SELLER, *, role: str = "USER", kyc_status: str = "VERIFIED",
           suspended: bool = False, token_version: int = 1) -> dict:
    token = encode_access_token(JWT, user_id=user_id, role=role, kyc_status=kyc_status,
                                suspended=suspended, token_version=token_version)
    return {"Authorization": f"Bearer {token}"}


def admin_headers() -> dict:
    return bearer(ADMIN, role="ADMIN", kyc_status="NOT_SUBMITTED")


class Harness:
    def __init__(self) -> None:
        self.repo = InMemoryAuctionRepository()
        self.events = InMemoryAuctionEventPublisher()
        self.versions = InMemoryTokenVersions()
        self.app = build_app(SETTINGS, self.repo, publisher=self.events,
                             token_versions=self.versions, jwt_settings=JWT)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    @property
    def service(self):
        return self.app.state.auction_service

    def create(self, headers=None, **overrides):
        now = datetime.now(UTC)
        body = {
            "title": "Vintage film camera",
            "category": "cameras",
            "starting_price": "100.00",
            "opens_at": (now + timedelta(minutes=5)).isoformat(),
            "closes_at": (now + timedelta(days=2)).isoformat(),
        } | overrides
        return self.client.post("/api/v1/auctions", json=body, headers=headers or bearer())

    def created(self, **overrides) -> str:
        response = self.create(**overrides)
        assert response.status_code == 201, response.text
        return response.json()["auction_id"]

    def publish(self, auction_id: str, headers=None):
        return self.client.post(f"/api/v1/auctions/{auction_id}/publish",
                                headers=headers or bearer())

    def operate(self, auction_id: str, event: str):
        return self.client.post(f"/api/v1/auctions/{auction_id}/events", json={"event": event},
                                headers=admin_headers())

    def drive(self, auction_id: str, *events: str) -> dict:
        response = self.client.get(f"/api/v1/auctions/{auction_id}")
        for event in events:
            if event == "publish":
                response = self.publish(auction_id)
            elif event == "cancel":
                response = self.client.post(f"/api/v1/auctions/{auction_id}/cancel",
                                            headers=bearer())
            else:
                response = self.operate(auction_id, event)
            assert response.status_code == 200, (event, response.text)
        return response.json()


def draft(**overrides) -> Auction:
    values = {
        "auction_id": uuid4(), "seller_id": SELLER, "title": "Lamp", "description": "",
        "category": "home", "starting_price": Decimal("5.00"), "reserve_price": None,
        "currency": "USD", "opens_at": NOW + timedelta(minutes=1),
        "closes_at": NOW + timedelta(hours=1), "now": NOW,
    } | overrides
    return new_draft(**values)
