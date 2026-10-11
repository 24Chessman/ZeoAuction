"""CT-3 as served over HTTP, validated against contracts/openapi/internal/pricing.v1.yaml."""

from fastapi.testclient import TestClient

from app.main import build_app
from app.settings import Settings
from tests.support import AUCTION, Clock, bid, make_service
from zeo_common.contract_testing import assert_matches_contract

CT3 = "openapi/internal/pricing.v1.yaml"
SETTINGS = Settings(database_url="", redis_url="", kafka_bootstrap_servers="")


def client_with(service=None):
    return TestClient(build_app(SETTINGS, service=service))


def test_min_increment_matches_the_contract():
    response = client_with().get(f"/api/v1/pricing/{AUCTION}/min-increment",
                                 params={"current_price": "1250.00"})
    assert response.status_code == 200
    body = response.json()
    assert_matches_contract(body, CT3, "/components/schemas/MinIncrement")
    assert (body["min_increment"], body["min_next_bid"], body["hot"]) == (
        "25.00", "1275.00", False)


async def test_velocity_matches_the_contract():
    clock = Clock()
    service = make_service(clock)
    for seq in range(1, 31):
        await service.on_bid_accepted(bid(seq, clock.now, "80.00"))
    client = client_with(service)
    body = client.get(f"/api/v1/pricing/{AUCTION}/velocity").json()
    assert_matches_contract(
        body, CT3,
        "/paths/~1pricing~1{auctionId}~1velocity/get/responses/200/content/application~1json/schema")
    assert (body["bids_per_minute"], body["hot"]) == (30.0, True)
    quote = client.get(f"/api/v1/pricing/{AUCTION}/min-increment",
                       params={"current_price": "80.00"}).json()
    assert (quote["min_increment"], quote["hot"]) == ("2.00", True)


def test_money_must_be_a_two_decimal_string():
    client = client_with()
    for bad in ("12.5", "-1.00", "abc", "1e3"):
        response = client.get(f"/api/v1/pricing/{AUCTION}/min-increment",
                              params={"current_price": bad})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
    assert client.get(f"/api/v1/pricing/{AUCTION}/min-increment").status_code == 422


def test_auction_id_must_be_a_uuid():
    response = client_with().get("/api/v1/pricing/not-a-uuid/min-increment",
                                 params={"current_price": "1.00"})
    assert response.status_code == 422
