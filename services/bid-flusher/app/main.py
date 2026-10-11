"""Bid batch flusher (worker) — see services/bid-flusher/README.md.

The HTTP surface is health, readiness and metrics only; the work happens in a background
task started with the app: an optional Kafka replay, then the flush loop.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.flusher import BatchFlusher, BatchPolicy, FlusherMetrics
from app.replay import KafkaEventSource, replay_bid_events
from app.settings import Settings
from app.store import PostgresBidStore
from zeo_common import create_app
from zeo_common.db import create_pool, postgres_check
from zeo_common.redis import create_redis, redis_check

logger = logging.getLogger(__name__)


def build_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="bid-flusher",
        version="0.2.0",
        description="ZeoAuction Bid batch flusher (worker).",
    )
    metrics = FlusherMetrics(app.state.metrics)
    app.state.flusher_metrics = metrics

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs infra
        if not start_worker:
            yield
            return
        redis = create_redis(settings.redis_url)
        pool = await create_pool(settings.database_url)
        store = PostgresBidStore(pool)
        app.state.readiness.add_check("redis", redis_check(redis))
        app.state.readiness.add_check("postgres", postgres_check(pool))
        flusher = BatchFlusher(
            redis, store,
            BatchPolicy(settings.batch_max_size, settings.batch_max_age_ms / 1000),
            metrics,
        )
        stop = asyncio.Event()

        async def work() -> None:
            if settings.replay_on_start:
                try:
                    report = await replay_bid_events(
                        KafkaEventSource(settings.kafka_bootstrap_servers), store, redis
                    )
                    metrics.replayed.inc(report.rows_restored)
                except Exception:
                    logger.exception("Start-up replay failed; continuing with the flush loop")
            await flusher.run(stop, settings.poll_interval_ms / 1000)

        task = asyncio.create_task(work())
        try:
            yield
        finally:
            stop.set()
            await task
            await pool.close()
            await redis.aclose()

    app.router.lifespan_context = lifespan
    return app


app = build_app()
