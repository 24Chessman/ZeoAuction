"""Order client adapter for Search & Analytics (Plan 6, #75).

The search service does NOT own an orders table; it queries payment-escrow
over HTTP to build the seller dashboard.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
from typing import Protocol
from uuid import UUID

import httpx

logger = logging.getLogger("search.order_client")


@dataclass(frozen=True)
class SellerOrderInfo:
    order_id: UUID
    auction_id: UUID
    state: str  # e.g. IN_ESCROW, SHIPPED, RELEASED, REFUNDED
    captured_amount: Decimal
    fee_amount: Decimal
    currency: str
    shipped_at: datetime | None
    protection_window_days: int = 7


class OrderClient(Protocol):
    async def get_seller_orders(self, seller_id: UUID) -> list[SellerOrderInfo]: ...


class InMemoryOrderClient:
    """Test double. Supply {seller_id: [SellerOrderInfo, ...]}."""

    def __init__(self, orders: dict[UUID, list[SellerOrderInfo]] | None = None) -> None:
        self._orders: dict[UUID, list[SellerOrderInfo]] = dict(orders) if orders else {}

    async def get_seller_orders(self, seller_id: UUID) -> list[SellerOrderInfo]:
        return list(self._orders.get(seller_id, []))


class HttpOrderClient:
    def __init__(self, base_url: str, internal_token: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self.timeout = timeout

    async def get_seller_orders(self, seller_id: UUID) -> list[SellerOrderInfo]:
        url = f"{self.base_url}/api/v1/internal/seller/{seller_id}/orders"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.get(url, headers={"X-Internal-Token": self.internal_token})
            res.raise_for_status()
            data = res.json()

        result: list[SellerOrderInfo] = []
        for item in data:
            shipped_str = item.get("shipped_at")
            shipped_at = (
                datetime.fromisoformat(shipped_str.replace("Z", "+00:00"))
                if shipped_str
                else None
            )
            result.append(
                SellerOrderInfo(
                    order_id=UUID(item["order_id"]),
                    auction_id=UUID(item["auction_id"]),
                    state=item["state"],
                    captured_amount=Decimal(str(item["captured_amount"])),
                    fee_amount=Decimal(str(item["fee_amount"])),
                    currency=item["currency"],
                    shipped_at=shipped_at,
                    protection_window_days=item.get("protection_window_days", 7),
                )
            )
        return result
