"""CT-1 consumer: auction state from Auction Orchestration.

Contract: contracts/openapi/internal/auction-state.v1.yaml. Every bid reads the live state;
the cache is only the declared fallback. While the breaker is open (or a call fails), a
snapshot under ``cache_seconds`` old is used, otherwise the bid is refused with
``AUCTION_STATE_UNAVAILABLE`` rather than accepted against an unknown state.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import httpx

from app.adapters.circuit_breaker import CircuitBreaker, CircuitOpen
from zeo_common import parse_money

logger = logging.getLogger(__name__)


class AuctionNotFound(Exception):
    pass


class AuctionStateUnavailable(Exception):
    pass


@dataclass(frozen=True)
class AuctionSnapshot:
    auction_id: UUID
    seller_id: UUID
    state: str
    bid_permitted: bool
    currency: str
    starting_price: Decimal
    closes_at: datetime | None
    as_of: datetime


def parse_snapshot(body: dict) -> AuctionSnapshot:
    closes_at = body.get("closes_at")
    return AuctionSnapshot(
        auction_id=UUID(body["auction_id"]),
        seller_id=UUID(body["seller_id"]),
        state=body["state"],
        bid_permitted=bool(body["bid_permitted"]),
        currency=body["currency"],
        starting_price=parse_money(body.get("starting_price", "0.00")),
        closes_at=datetime.fromisoformat(closes_at) if closes_at else None,
        as_of=datetime.fromisoformat(body["as_of"]),
    )


class AuctionStateClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        breaker: CircuitBreaker,
        *,
        cache_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self.breaker = breaker
        self.cache_seconds = cache_seconds
        self._clock = clock
        self._cache: dict[UUID, tuple[float, AuctionSnapshot]] = {}

    async def _fetch(self, auction_id: UUID) -> AuctionSnapshot | None:
        response = await self.http.get(f"/api/v1/auctions/{auction_id}/state")
        if response.status_code == 404:
            return None  # an answer, not a dependency failure
        response.raise_for_status()
        return parse_snapshot(response.json())

    async def get_state(self, auction_id: UUID) -> AuctionSnapshot:
        try:
            snapshot = await self.breaker.call(lambda: self._fetch(auction_id))
        except (CircuitOpen, httpx.HTTPError, KeyError, ValueError) as exc:
            cached = self._cache.get(auction_id)
            if cached and self._clock() - cached[0] < self.cache_seconds:
                logger.warning("CT-1 unavailable (%s); using cached state", exc)
                return cached[1]
            raise AuctionStateUnavailable(str(auction_id)) from exc
        if snapshot is None:
            self._cache.pop(auction_id, None)
            raise AuctionNotFound(str(auction_id))
        self._cache[auction_id] = (self._clock(), snapshot)
        return snapshot
