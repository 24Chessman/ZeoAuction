"""CT-4 consumer: open the settlement order in Payment & Escrow (saga S1, #33).

Contract: contracts/openapi/internal/settlement.v1.yaml. Called by the lifecycle timer for every
CLOSED auction with a winner and no order yet. Behind the Orchestration -> Payment breaker
(SDD Table 2.2: opens after 3 failures in 30 s). Any failure, or an open breaker, raises
:class:`PaymentUnavailable`; the auction stays CLOSED and the next timer pass retries with the
same Idempotency-Key. Settlement is deferred, never abandoned.
"""

import time
from collections.abc import Callable
from uuid import UUID

import httpx

from app.domain.settlement import SettlementRequest
from zeo_common import format_money
from zeo_common.circuit_breaker import CircuitBreaker, CircuitOpen


class PaymentUnavailable(Exception):
    pass


class SettlementRefused(Exception):
    """Payment answered definitively (409 or 422); retrying the same request will not help."""


def payment_breaker(clock: Callable[[], float] = time.monotonic) -> CircuitBreaker:
    return CircuitBreaker("payment", failure_threshold=3, window_seconds=30, reset_seconds=10,
                          clock=clock)


class PaymentClient:
    def __init__(self, http: httpx.AsyncClient, breaker: CircuitBreaker, internal_token: str):
        self.http = http
        self.breaker = breaker
        self.internal_token = internal_token

    async def _post(self, request: SettlementRequest) -> httpx.Response:
        response = await self.http.post(
            "/api/v1/internal/orders",
            json={
                "auction_id": str(request.auction_id),
                "buyer_id": str(request.buyer_id),
                "seller_id": str(request.seller_id),
                "winning_bid_id": str(request.winning_bid_id),
                "winning_bid_amount": format_money(request.winning_bid_amount),
                "currency": request.currency,
            },
            headers={"Idempotency-Key": request.idempotency_key,
                     "X-Internal-Token": self.internal_token},
        )
        if response.status_code in (409, 422):
            return response  # an answer, not a dependency failure
        response.raise_for_status()
        return response

    async def open_order(self, request: SettlementRequest) -> UUID:
        try:
            response = await self.breaker.call(lambda: self._post(request))
        except (CircuitOpen, httpx.HTTPError) as exc:
            raise PaymentUnavailable(str(exc)) from exc
        body = response.json()
        if response.status_code >= 400:
            raise SettlementRefused(f"{body.get('code')}: {body.get('message')}")
        try:
            return UUID(body["order_id"])
        except (KeyError, ValueError, TypeError) as exc:
            raise PaymentUnavailable("Payment answered without an order_id") from exc
