"""Auction Orchestration — see services/auction-orchestrator/README.md."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from app.adapters.auction_repo import (
    AuctionRepository,
    InMemoryAuctionRepository,
    PostgresAuctionRepository,
)
from app.adapters.bid_events import BidEventsConsumer
from app.adapters.kafka_producer import (
    AuctionEventPublisher,
    InMemoryAuctionEventPublisher,
    KafkaAuctionEventPublisher,
)
from app.api import router
from app.service import AuctionMetrics, AuctionService
from app.settings import Settings
from app.timers import LifecycleTimer
from zeo_common import create_app
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check
from zeo_common.gateway import RedisTokenVersions, TokenVersions, install_gateway
from zeo_common.redis import create_redis, redis_check

VERSION = "0.3.0"


def build_app(
    settings: Settings | None = None,
    repository: AuctionRepository | None = None,
    *,
    publisher: AuctionEventPublisher | None = None,
    token_versions: TokenVersions | None = None,
    jwt_settings: JwtSettings | None = None,
) -> FastAPI:
    """Create the service. Tests pass ``repository``; otherwise it is built at start-up."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="auction-orchestrator",
        version=VERSION,
        description="ZeoAuction Auction Orchestration.",
    )
    install_auth(app, jwt_settings)
    install_gateway(app, token_versions)
    metrics = AuctionMetrics(app.state.metrics)
    drain_grace = timedelta(seconds=settings.drain_grace_seconds)

    def attach(repo: AuctionRepository, events: AuctionEventPublisher) -> AuctionService:
        service = AuctionService(repo, events, metrics, drain_grace=drain_grace)
        app.state.auction_service = service
        return service

    attach(repository or InMemoryAuctionRepository(),
           publisher or InMemoryAuctionEventPublisher())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs infra
        if repository is not None or settings.repository != "postgres":
            yield
            return
        pool = await create_pool(settings.database_url)
        app.state.readiness.add_check("postgres", postgres_check(pool))
        redis = None
        if settings.check_token_freshness:
            redis = create_redis(settings.redis_url)
            install_gateway(app, RedisTokenVersions(redis))
            app.state.readiness.add_check("redis", redis_check(redis))
        events: AuctionEventPublisher = publisher or InMemoryAuctionEventPublisher()
        if publisher is None and settings.publisher == "kafka":
            kafka = KafkaAuctionEventPublisher.connect(settings.kafka_bootstrap_servers)
            await kafka.start()
            app.state.readiness.add_check("kafka", kafka.ready)
            events = kafka
        service = attach(PostgresAuctionRepository(pool), events)
        timer = LifecycleTimer(service, settings.timer_interval_seconds)
        if settings.run_timer:
            timer.start()
        consumer_task = None
        if settings.consume_bids:
            consumer = BidEventsConsumer.connect(
                settings.kafka_bootstrap_servers, service.on_bid_accepted
            )
            consumer_task = asyncio.create_task(consumer.run(), name="bid-events-consumer")
        try:
            yield
        finally:
            await timer.stop()
            if consumer_task is not None:
                consumer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer_task
            if isinstance(events, KafkaAuctionEventPublisher):
                await events.stop()
            if redis is not None:
                await redis.aclose()
            await pool.close()

    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


app = build_app()
