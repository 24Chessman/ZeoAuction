"""Contract fakes for the bid service's dependencies.

The HTTP fakes answer CT-1 and CT-3 through ``httpx.MockTransport`` and validate every body
they serve against the published contract, so a fake can never drift from the provider it
stands in for. The other fakes implement the adapter interfaces in memory.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx

from zeo_common import format_money, parse_money
from zeo_common.contract_testing import assert_matches_contract

SELLER_ID = UUID("00000000-0000-4000-8000-000000000002")
AUCTION_ID = UUID("00000000-0000-4000-8000-000000000201")
CT1 = ("openapi/internal/auction-state.v1.yaml", "/components/schemas/AuctionState")
CT3 = ("openapi/internal/pricing.v1.yaml", "/components/schemas/MinIncrement")


class ManualClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeAuction:
    auction_id: UUID = AUCTION_ID
    seller_id: UUID = SELLER_ID
    state: str = "OPEN"
    currency: str = "USD"
    starting_price: str = "100.00"
    closes_at: datetime | None = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(days=2)
    )

    def body(self) -> dict:
        return {
            "auction_id": str(self.auction_id),
            "seller_id": str(self.seller_id),
            "state": self.state,
            "bid_permitted": self.state in ("OPEN", "EXTENDED"),
            "currency": self.currency,
            "starting_price": self.starting_price,
            "closes_at": None if self.closes_at is None else self.closes_at.isoformat(),
            "as_of": datetime.now(UTC).isoformat(),
        }


class FakeOrchestrator:
    """CT-1 provider. ``failing = True`` makes every call a 500."""

    def __init__(self, *auctions: FakeAuction) -> None:
        self.auctions = {a.auction_id: a for a in (auctions or (FakeAuction(),))}
        self.failing = False
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.failing:
            return httpx.Response(500, json={"code": "INTERNAL_ERROR"})
        parts = request.url.path.strip("/").split("/")
        auction = self.auctions.get(UUID(parts[3]))
        if auction is None:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": "no",
                                             "request_id": "00000000-0000-4000-8000-000000000000"})
        body = auction.body()
        assert_matches_contract(body, *CT1)
        return httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), base_url="http://orchestrator"
        )


class FakePricing:
    """CT-3 provider with a flat increment. ``failing = True`` makes every call a 503."""

    def __init__(self, increment: str = "5.00") -> None:
        self.increment = increment
        self.failing = False
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.failing:
            return httpx.Response(503)
        auction_id = request.url.path.strip("/").split("/")[3]
        current = parse_money(request.url.params["current_price"])
        increment = parse_money(self.increment)
        body = {
            "auction_id": auction_id,
            "min_increment": self.increment,
            "min_next_bid": format_money(current + increment),
            "hot": False,
            "computed_at": datetime.now(UTC).isoformat(),
        }
        assert_matches_contract(body, *CT3)
        return httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), base_url="http://pricing"
        )


class FakeFunds:
    def __init__(self, limit: str = "100000.00", per_bidder: dict[UUID, str] | None = None) -> None:
        self.limit = Decimal(limit)
        self.per_bidder = {k: Decimal(v) for k, v in (per_bidder or {}).items()}

    async def available(self, bidder_id: UUID) -> Decimal:
        return self.per_bidder.get(bidder_id, self.limit)


class FakeAioKafkaProducer:
    """Stands in for ``aiokafka.AIOKafkaProducer``: records what was sent and acknowledged."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.started = False
        self.fail_next = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> object:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("broker unavailable")
        self.sent.append((topic, key, value))
        return object()

    async def partitions_for(self, topic: str) -> set[int]:
        return set(range(12))
