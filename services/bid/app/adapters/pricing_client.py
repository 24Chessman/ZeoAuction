"""CT-3 consumer: the minimum bid increment from the Pricing Engine.

Contract: contracts/openapi/internal/pricing.v1.yaml. :class:`HttpPricingClient` calls the
Pricing Engine (``PRICING_MODE=http``); :class:`StubPricingClient` answers with the same shape
from the fixed tier table, for runs without the engine. While the CT-3 breaker is open (5
failures in 10 s) the HTTP client falls back to the last increment cached in Redis
(``inc:{auction_id}``, 60 s, written by both the engine and this client) and flags the bid
``increment_stale``.

The tier table is the floor of every increment: the Pricing Engine's dynamic increment never
goes below it, and the fallback never does either (a cached increment from a lower price band
is raised to the tier). :func:`app.domain.conflict.replay` re-derives the winner with this
table, so a live bid can never clear a lower bar than the replay applies (AC-04). The table is
pinned to ``infra/postgres/init/51-pricing-dynamic.sql`` by ``tests/test_ct3_breaker.py``.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.adapters.circuit_breaker import CircuitBreaker, CircuitOpen
from zeo_common import format_money, parse_money

logger = logging.getLogger(__name__)

# (upper bound of current price, increment). The last tier has no upper bound.
INCREMENT_TIERS: tuple[tuple[Decimal | None, Decimal], ...] = (
    (Decimal("100.00"), Decimal("1.00")),
    (Decimal("500.00"), Decimal("5.00")),
    (Decimal("1000.00"), Decimal("10.00")),
    (Decimal("5000.00"), Decimal("25.00")),
    (None, Decimal("50.00")),
)


def tier_increment(current_price: Decimal) -> Decimal:
    for upper, increment in INCREMENT_TIERS:
        if upper is None or current_price < upper:
            return increment
    raise AssertionError("unreachable: the last tier is unbounded")


@dataclass(frozen=True)
class IncrementQuote:
    min_increment: Decimal
    min_next_bid: Decimal
    hot: bool = False
    stale: bool = False


class PricingClient(Protocol):
    async def quote(self, auction_id: UUID, current_price: Decimal) -> IncrementQuote: ...


class StubPricingClient:
    """CT-3 stand-in with the published response shape (Plan 2 risk mitigation)."""

    async def quote(self, auction_id: UUID, current_price: Decimal) -> IncrementQuote:
        increment = tier_increment(current_price)
        return IncrementQuote(min_increment=increment, min_next_bid=current_price + increment)


# inc:{auction_id} lifetime, SDD Table 4.3.
INCREMENT_CACHE_TTL_SECONDS = 60


def increment_cache_key(auction_id: UUID) -> str:
    return f"inc:{auction_id}"


class HttpPricingClient:
    def __init__(self, http: httpx.AsyncClient, breaker: CircuitBreaker, redis: Any) -> None:
        self.http = http
        self.breaker = breaker
        self.redis = redis

    async def _fetch(self, auction_id: UUID, current_price: Decimal) -> IncrementQuote:
        response = await self.http.get(
            f"/api/v1/pricing/{auction_id}/min-increment",
            params={"current_price": format_money(current_price)},
        )
        response.raise_for_status()
        body = response.json()
        return IncrementQuote(
            min_increment=parse_money(body["min_increment"]),
            min_next_bid=parse_money(body["min_next_bid"]),
            hot=bool(body["hot"]),
        )

    async def quote(self, auction_id: UUID, current_price: Decimal) -> IncrementQuote:
        try:
            quote = await self.breaker.call(lambda: self._fetch(auction_id, current_price))
        except (CircuitOpen, httpx.HTTPError, KeyError, ValueError) as exc:
            cached = await self.redis.get(increment_cache_key(auction_id))
            floor = tier_increment(current_price)
            increment = max(parse_money(cached), floor) if cached else floor
            logger.warning("CT-3 unavailable (%s); using %s increment", exc,
                           "cached" if cached else "tier-table")
            return IncrementQuote(
                min_increment=increment, min_next_bid=current_price + increment, stale=True
            )
        await self.redis.set(increment_cache_key(auction_id), format_money(quote.min_increment),
                             ex=INCREMENT_CACHE_TTL_SECONDS)
        return quote
