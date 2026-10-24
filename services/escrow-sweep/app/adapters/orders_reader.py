"""Reads orders with expired protection windows from payment.orders (Plan 6, #25).

Documented exception: the escrow sweep reads (never writes) the columns it scans:
    id, state, protection_window_ends_at
under the sweep_svc role (ADR-0006; infra/postgres/init/60-payment.sql).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class ExpiredOrder:
    order_id: UUID
    protection_window_ends_at: datetime


class OrdersReader(Protocol):
    async def expired_shipped_orders(self, now: datetime) -> list[ExpiredOrder]:
        """Find orders in state SHIPPED whose protection window has passed."""
        ...


class InMemoryOrdersReader:
    def __init__(self, orders: list[ExpiredOrder] | None = None) -> None:
        self.orders: list[ExpiredOrder] = list(orders) if orders else []

    async def expired_shipped_orders(self, now: datetime) -> list[ExpiredOrder]:
        return [o for o in self.orders if o.protection_window_ends_at <= now]


class PostgresOrdersReader:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def expired_shipped_orders(self, now: datetime) -> list[ExpiredOrder]:
        query = (
            "SELECT id, protection_window_ends_at FROM payment.orders "
            "WHERE state = 'SHIPPED' AND protection_window_ends_at <= $1 "
            "ORDER BY protection_window_ends_at ASC"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, now)
            return [
                ExpiredOrder(
                    order_id=row["id"],
                    protection_window_ends_at=row["protection_window_ends_at"],
                )
                for row in rows
            ]
