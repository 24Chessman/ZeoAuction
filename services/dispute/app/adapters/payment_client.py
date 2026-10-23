"""Payment client adapter for Dispute Management (Plan 6, #84).

Dispute Management never writes the payment ledger. It sends freeze, release,
and refund commands to Payment over a published contract (SDD §5.2.4).
"""

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Protocol
from uuid import UUID

import httpx

logger = logging.getLogger("dispute.payment_client")


@dataclass(frozen=True)
class OrderInfo:
    order_id: UUID
    auction_id: UUID
    buyer_id: UUID
    seller_id: UUID
    state: str
    protection_window_ends_at: datetime | None = None


class PaymentClient(Protocol):
    async def get_order(self, order_id: UUID) -> OrderInfo | None: ...
    async def freeze_order(self, order_id: UUID, reason: str = "dispute") -> bool: ...
    async def release_order(self, order_id: UUID, idempotency_key: str | None = None) -> bool: ...
    async def refund_order(
        self, order_id: UUID, fault: str, note: str | None = None, idempotency_key: str | None = None
    ) -> bool: ...


class InMemoryPaymentClient:
    def __init__(self, orders: dict[UUID, OrderInfo] | None = None) -> None:
        self.orders: dict[UUID, OrderInfo] = dict(orders) if orders else {}
        self.frozen: set[UUID] = set()
        self.released: set[UUID] = set()
        self.refunded: dict[UUID, str] = {}

    async def get_order(self, order_id: UUID) -> OrderInfo | None:
        return self.orders.get(order_id)

    async def freeze_order(self, order_id: UUID, reason: str = "dispute") -> bool:
        self.frozen.add(order_id)
        if order_id in self.orders:
            curr = self.orders[order_id]
            self.orders[order_id] = OrderInfo(
                order_id=curr.order_id,
                auction_id=curr.auction_id,
                buyer_id=curr.buyer_id,
                seller_id=curr.seller_id,
                state="DISPUTED",
                protection_window_ends_at=curr.protection_window_ends_at,
            )
        return True

    async def release_order(self, order_id: UUID, idempotency_key: str | None = None) -> bool:
        self.released.add(order_id)
        if order_id in self.orders:
            curr = self.orders[order_id]
            self.orders[order_id] = OrderInfo(
                order_id=curr.order_id,
                auction_id=curr.auction_id,
                buyer_id=curr.buyer_id,
                seller_id=curr.seller_id,
                state="RELEASED",
                protection_window_ends_at=curr.protection_window_ends_at,
            )
        return True

    async def refund_order(
        self, order_id: UUID, fault: str, note: str | None = None, idempotency_key: str | None = None
    ) -> bool:
        self.refunded[order_id] = fault
        if order_id in self.orders:
            curr = self.orders[order_id]
            self.orders[order_id] = OrderInfo(
                order_id=curr.order_id,
                auction_id=curr.auction_id,
                buyer_id=curr.buyer_id,
                seller_id=curr.seller_id,
                state="REFUNDED",
                protection_window_ends_at=curr.protection_window_ends_at,
            )
        return True


class HttpPaymentClient:
    def __init__(self, base_url: str, internal_token: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self.timeout = timeout

    async def get_order(self, order_id: UUID) -> OrderInfo | None:
        url = f"{self.base_url}/api/v1/orders/{order_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.get(url, headers={"X-Internal-Token": self.internal_token})
            if res.status_code == 404:
                return None
            res.raise_for_status()
            data = res.json()
            ends_at_str = data.get("protection_window_ends_at")
            ends_at = datetime.fromisoformat(ends_at_str.replace("Z", "+00:00")) if ends_at_str else None
            return OrderInfo(
                order_id=UUID(data["order_id"]),
                auction_id=UUID(data["auction_id"]),
                buyer_id=UUID(data["buyer_id"]),
                seller_id=UUID(data["seller_id"]),
                state=data["state"],
                protection_window_ends_at=ends_at,
            )

    async def freeze_order(self, order_id: UUID, reason: str = "dispute") -> bool:
        url = f"{self.base_url}/api/v1/internal/orders/{order_id}/freeze?reason={reason}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, headers={"X-Internal-Token": self.internal_token})
            return res.status_code == 200

    async def release_order(self, order_id: UUID, idempotency_key: str | None = None) -> bool:
        url = f"{self.base_url}/api/v1/internal/orders/{order_id}/release?trigger=adjudicate_seller"
        headers = {"X-Internal-Token": self.internal_token}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, headers=headers)
            return res.status_code in (200, 201)

    async def refund_order(
        self, order_id: UUID, fault: str, note: str | None = None, idempotency_key: str | None = None
    ) -> bool:
        url = f"{self.base_url}/api/v1/internal/orders/{order_id}/refund"
        headers = {"X-Internal-Token": self.internal_token}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, json={"fault": fault, "note": note}, headers=headers)
            return res.status_code in (200, 201)
