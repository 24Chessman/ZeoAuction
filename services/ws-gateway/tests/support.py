from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.main import build_app
from app.settings import Settings
from zeo_common.auth import JwtSettings, encode_access_token

JWT = JwtSettings(secret="ws-gateway-test-secret-32-bytes!!!")
AUCTION = "00000000-0000-4000-8000-000000000201"
ALICE = UUID("00000000-0000-4000-8000-000000000004")
BOB = UUID("00000000-0000-4000-8000-000000000005")


def settings(**overrides) -> Settings:
    values = {"redis_url": "unused", "kafka_bootstrap_servers": "unused",
              "consumer_group": "test", "consume": False, "use_redis": False} | overrides
    return Settings(**values)


def token(user_id: UUID = ALICE, *, now: datetime | None = None, **claims) -> str:
    values = {"role": "USER", "kyc_status": "NOT_SUBMITTED", "suspended": False} | claims
    return encode_access_token(JWT, user_id=user_id, now=now, **values)


def client(**overrides) -> TestClient:
    return TestClient(build_app(settings(**overrides), jwt_settings=JWT))


def url(user_id: UUID = ALICE, path: str = "/ws", **claims) -> str:
    return f"{path}?access_token={token(user_id, **claims)}"


def bid_event(seq: int, bidder: UUID, amount: str = "120.00", auction: str = AUCTION,
              accepted_at: datetime | None = None, bid_id: str | None = None) -> dict:
    accepted = accepted_at or datetime.now(UTC)
    return {
        "event_id": str(uuid4()), "schema_version": 1, "auction_id": auction,
        "bid_id": bid_id or str(uuid4()), "bidder_id": str(bidder),
        "seller_id": "00000000-0000-4000-8000-000000000002", "amount": amount,
        "currency": "USD", "server_seq": seq,
        "accepted_at": accepted.isoformat().replace("+00:00", "Z"),
        "idempotency_key": f"key-{uuid4()}",
    }


def state_event(event: str, from_state: str, to_state: str, **extra) -> dict:
    closes = (datetime.now(UTC) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    return {
        "event_id": str(uuid4()), "schema_version": 1, "auction_id": AUCTION, "event": event,
        "from_state": from_state, "to_state": to_state, "closes_at": closes,
        "extension_count": 1, "winning_bid_id": None, "actor_id": None,
        "occurred_at": closes,
    } | extra
