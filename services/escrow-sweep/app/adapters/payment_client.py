"""Client to trigger release on the Payment & Escrow service (Plan 6, #25).

Releases through POST /api/v1/internal/orders/{id}/release?trigger=sweep_expiry
using the idempotency key order:{id}:release (SDD 5.2.3, ADR-0006).
"""

import logging
from typing import Any, Protocol
from uuid import UUID

import httpx

logger = logging.getLogger("escrow-sweep")


class PaymentReleaseClient(Protocol):
    async def release_order(self, order_id: UUID) -> bool:
        """Ask Payment service to release funds for order_id."""
        ...


class InMemoryPaymentReleaseClient:
    def __init__(self) -> None:
        self.released: set[UUID] = set()

    async def release_order(self, order_id: UUID) -> bool:
        self.released.add(order_id)
        return True


class HttpPaymentReleaseClient:
    def __init__(self, base_url: str, internal_token: str, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self.timeout = timeout_seconds

    async def release_order(self, order_id: UUID) -> bool:
        url = f"{self.base_url}/api/v1/internal/orders/{order_id}/release?trigger=sweep_expiry"
        headers = {
            "X-Internal-Token": self.internal_token,
            "Idempotency-Key": f"order:{order_id}:release",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                res = await client.post(url, headers=headers)
                if res.status_code in (200, 201):
                    return True
                logger.error("Payment release for order %s returned HTTP %d: %s",
                             order_id, res.status_code, res.text)
                return False
            except Exception as exc:
                logger.exception("Payment release call failed for order %s: %s", order_id, exc)
                return False
