"""Escrow sweep (cron) — see services/escrow-sweep/README.md.

Render runs ``python -m app.sweep`` every minute as a Cron Job (ADR-0006); Compose runs it in a
60-second loop. Each run must be idempotent: overlapping runs are safe because every release
carries the key ``order:{id}:release``.

Finds SHIPPED orders whose protection_window_ends_at <= now, releases them, and tracks
escrow_sweep_lag_seconds (AC-12: release within 5 minutes / 300 s).
"""

import asyncio
from datetime import UTC, datetime
import logging
import os
from typing import Any
from uuid import UUID

from prometheus_client import CollectorRegistry, Counter, Gauge, REGISTRY

from app.adapters.orders_reader import (
    ExpiredOrder,
    InMemoryOrdersReader,
    OrdersReader,
    PostgresOrdersReader,
)
from app.adapters.payment_client import (
    HttpPaymentReleaseClient,
    InMemoryPaymentReleaseClient,
    PaymentReleaseClient,
)
from zeo_common.logging_setup import configure_logging

logger = logging.getLogger("escrow-sweep")

# Metrics
registry: CollectorRegistry = REGISTRY
try:
    SWEEP_LAG_SECONDS = Gauge(
        "escrow_sweep_lag_seconds",
        "Lag in seconds between protection window expiry and sweep release execution.",
        registry=registry,
    )
    SWEEP_RELEASED_TOTAL = Counter(
        "escrow_sweep_released_total",
        "Total orders released by the escrow sweep.",
        registry=registry,
    )
except ValueError:  # pragma: no cover
    SWEEP_LAG_SECONDS = registry._names_to_collectors["escrow_sweep_lag_seconds"]  # type: ignore
    SWEEP_RELEASED_TOTAL = registry._names_to_collectors["escrow_sweep_released_total"]  # type: ignore


async def sweep_once(
    reader: OrdersReader,
    client: PaymentReleaseClient,
    *,
    now: datetime | None = None,
) -> int:
    """Execute one sweep pass: find expired orders and release them."""
    current_time = now or datetime.now(UTC)
    expired = await reader.expired_shipped_orders(current_time)

    if not expired:
        SWEEP_LAG_SECONDS.set(0.0)
        logger.info("escrow sweep run: 0 expired orders found")
        return 0

    max_lag = 0.0
    released_count = 0

    for item in expired:
        lag = max(0.0, (current_time - item.protection_window_ends_at).total_seconds())
        if lag > max_lag:
            max_lag = lag

        success = await client.release_order(item.order_id)
        if success:
            released_count += 1
            SWEEP_RELEASED_TOTAL.inc()
            logger.info("escrow sweep: released order %s (lag: %.1fs)", item.order_id, lag)

    SWEEP_LAG_SECONDS.set(max_lag)
    if max_lag > 300.0:
        logger.warning(
            "ALERT: escrow_sweep_lag_seconds %.1f exceeds 300s SLA threshold (AC-12)", max_lag
        )

    logger.info("escrow sweep finished: %d/%d order(s) released", released_count, len(expired))
    return released_count


def run_once(
    reader: OrdersReader | None = None,
    client: PaymentReleaseClient | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Synchronous entry point that runs the async sweep_once."""
    r = reader or InMemoryOrdersReader()
    c = client or InMemoryPaymentReleaseClient()
    return asyncio.run(sweep_once(r, c, now=now))


def main() -> None:
    configure_logging("escrow-sweep")
    db_url = os.getenv("DATABASE_URL")
    payment_url = os.getenv("PAYMENT_SERVICE_URL", "http://payment-escrow:8000")
    internal_token = os.getenv("INTERNAL_SERVICE_TOKEN", "")

    if db_url:  # pragma: no cover
        from zeo_common.db import create_pool
        async def run_live():
            pool = await create_pool(db_url)
            try:
                reader = PostgresOrdersReader(pool)
                client = HttpPaymentReleaseClient(payment_url, internal_token)
                return await sweep_once(reader, client)
            finally:
                await pool.close()
        released = asyncio.run(run_live())
    else:
        released = run_once()

    logger.info("escrow sweep finished: %d order(s) released", released)


if __name__ == "__main__":
    main()
