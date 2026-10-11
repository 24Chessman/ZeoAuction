from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.adapters.kafka_producer import InMemorySettlementEventPublisher
from app.adapters.repository import InMemoryPaymentRepository
from app.domain.fees import ACTIVE_FEE
from app.domain.orders import Order, SettlementRequest, open_order
from app.main import build_app
from app.payment_port.mock_adapter import MockPaymentAdapter
from app.service import capture_breaker
from app.settings import Settings
from zeo_common.auth import JwtSettings, encode_access_token

JWT = JwtSettings(secret="payment-test-secret-32-bytes-long!!")
INTERNAL = {"X-Internal-Token": "payment-test-internal-token"}
SETTINGS = Settings(database_url="unused", repository="memory", kafka_bootstrap_servers="unused",
                    internal_token=INTERNAL["X-Internal-Token"])
BUYER = UUID("00000000-0000-4000-8000-000000000003")
LOSER = UUID("00000000-0000-4000-8000-000000000004")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
ADMIN = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def bearer(user_id: UUID = BUYER, *, role: str = "USER") -> dict:
    token = encode_access_token(JWT, user_id=user_id, role=role, kyc_status="VERIFIED",
                                suspended=False)
    return {"Authorization": f"Bearer {token}"}


def request(amount: str = "1250.00", **overrides) -> SettlementRequest:
    values = {
        "auction_id": uuid4(), "buyer_id": BUYER, "seller_id": SELLER, "winning_bid_id": uuid4(),
        "winning_bid_amount": Decimal(amount), "currency": "INR",
    } | overrides
    return SettlementRequest(**values)


def body_of(req: SettlementRequest) -> dict:
    return {
        "auction_id": str(req.auction_id), "buyer_id": str(req.buyer_id),
        "seller_id": str(req.seller_id), "winning_bid_id": str(req.winning_bid_id),
        "winning_bid_amount": f"{req.winning_bid_amount:.2f}", "currency": req.currency,
    }


def order(amount: str = "1250.00", **overrides) -> Order:
    return open_order(request(amount, **overrides), order_id=uuid4(), saga_id=uuid4(),
                      fee=ACTIVE_FEE, provider="mock", now=NOW,
                      payment_window=timedelta(hours=48))


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


class Harness:
    """The service over HTTP, with an in-memory repository, the mock adapter and a fake clock."""

    def __init__(self, port: MockPaymentAdapter | None = None) -> None:
        self.repo = InMemoryPaymentRepository()
        self.events = InMemorySettlementEventPublisher()
        self.port = port or MockPaymentAdapter()
        self.app = build_app(SETTINGS, self.repo, port=self.port, publisher=self.events,
                             jwt_settings=JWT)
        self.clock = Clock()
        self.service.clock = self.clock
        self.service.breaker = capture_breaker(clock=lambda: self.clock.now.timestamp())
        self.client = TestClient(self.app, raise_server_exceptions=False)

    @property
    def service(self):
        return self.app.state.payment_service

    def open(self, req: SettlementRequest | None = None, key: str = "settle-key-1"):
        req = req or request()
        return self.client.post("/api/v1/internal/orders", json=body_of(req),
                                headers=INTERNAL | {"Idempotency-Key": key})

    def opened(self, req: SettlementRequest | None = None) -> dict:
        response = self.open(req)
        assert response.status_code == 201, response.text
        return response.json()

    def checkout(self, order_id: str, user: UUID = BUYER):
        return self.client.post(f"/api/v1/orders/{order_id}/checkout", headers=bearer(user))

    def pay(self, order_id: str, checkout: dict | None = None, *, signature: str | None = None,
            user: UUID = BUYER):
        checkout = checkout or self.checkout(order_id, user).json()
        simulated = checkout["simulated_payment"]
        return self.client.post(
            f"/api/v1/orders/{order_id}/payment",
            json={"provider_order_id": checkout["provider_order_id"],
                  "payment_id": simulated["payment_id"],
                  "signature": signature or simulated["signature"]},
            headers=bearer(user) | {"Idempotency-Key": f"pay-{order_id}"},
        )

    def ledger(self, order_id: str) -> list[dict]:
        response = self.client.get(f"/api/v1/orders/{order_id}/ledger",
                                   headers=bearer(ADMIN, role="ADMIN"))
        assert response.status_code == 200, response.text
        return response.json()
