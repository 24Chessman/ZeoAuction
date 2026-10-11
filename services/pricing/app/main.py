"""Pricing Engine — see services/pricing/README.md."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.adapters.bid_consumer import BidEventsConsumer
from app.adapters.repository import (
    InMemoryPricingRepository,
    PostgresPricingRepository,
    PricingRepository,
)
from app.api import router
from app.domain.hot_auction import HotAuctions, HotPolicy
from app.domain.velocity import VelocityTracker
from app.service import PricingMetrics, PricingService
from app.settings import Settings
from zeo_common import create_app
from zeo_common.db import create_pool, postgres_check
from zeo_common.redis import create_redis, redis_check

VERSION = "0.2.0"
logger = logging.getLogger(__name__)


class _NoCache:
    """Memory mode without Redis: CT-3 still answers, nothing is cached."""

    async def set(self, *args: object, **kwargs: object) -> None:
        return None


async def flush_forever(service: PricingService, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await service.flush()
        except Exception:
            logger.exception("Velocity flush failed; retrying next interval")


def build_app(
    settings: Settings | None = None,
    *,
    service: PricingService | None = None,
) -> FastAPI:
    """Create the service. Tests pass ``service``; otherwise it is built at start-up."""
    settings = settings or Settings.from_env()
    app = create_app(service_name="pricing", version=VERSION,
                     description="ZeoAuction Pricing Engine.")
    metrics = PricingMetrics(app.state.metrics)

    def build_service(repository: PricingRepository, cache: Any) -> PricingService:
        return PricingService(
            tracker=VelocityTracker(settings.window_seconds, settings.bucket_seconds),
            hot=HotAuctions(HotPolicy(settings.hot_enter_bpm, settings.hot_exit_bpm)),
            repository=repository,
            cache=cache,
            metrics=metrics,
            saturation_bpm=settings.saturation_bpm,
            cache_ttl_seconds=settings.cache_ttl_seconds,
        )

    app.state.pricing_service = service or build_service(InMemoryPricingRepository(), _NoCache())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs infra
        if service is not None or settings.repository != "postgres":
            yield
            return
        pool = await create_pool(settings.database_url)
        redis = create_redis(settings.redis_url)
        app.state.readiness.add_check("postgres", postgres_check(pool))
        app.state.readiness.add_check("redis", redis_check(redis))
        live = build_service(PostgresPricingRepository(pool), redis)
        await live.warm_up()
        app.state.pricing_service = live
        tasks = [asyncio.create_task(
            flush_forever(live, settings.flush_interval_seconds), name="velocity-flush")]
        if settings.consume_bids:
            consumer = BidEventsConsumer.connect(settings.kafka_bootstrap_servers,
                                                 live.on_bid_accepted)
            tasks.append(asyncio.create_task(consumer.run(), name="bid-events-consumer"))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            with contextlib.suppress(Exception):
                await live.flush()
            await redis.aclose()
            await pool.close()

    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


app = build_app()
