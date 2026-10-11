"""Bid Processing — see services/bid/README.md."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from app.adapters.auction_client import AuctionStateClient
from app.adapters.bid_repo import BidRepository, PostgresBidRepository
from app.adapters.circuit_breaker import CircuitBreaker
from app.adapters.funds import StubFunds
from app.adapters.kafka_producer import InMemoryBidEventPublisher, KafkaBidEventPublisher
from app.adapters.price_buffer import RedisPriceBuffer
from app.adapters.pricing_client import HttpPricingClient, PricingClient, StubPricingClient
from app.api import router
from app.domain.idempotency import IdempotencyGuard
from app.service import BidMetrics, BidService
from app.settings import Settings
from zeo_common import create_app
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check
from zeo_common.redis import create_redis, redis_check

VERSION = "0.2.0"


@dataclass
class BidDependencies:
    """Everything the routes need; tests build one from fakes."""

    service: BidService
    bids: BidRepository


def _breaker(name: str, settings: Settings) -> CircuitBreaker:
    return CircuitBreaker(
        name,
        failure_threshold=settings.breaker_failures,
        window_seconds=settings.breaker_window_seconds,
        reset_seconds=settings.breaker_reset_seconds,
    )


def build_app(
    settings: Settings | None = None,
    *,
    dependencies: Callable[[BidMetrics], BidDependencies] | None = None,
    jwt_settings: JwtSettings | None = None,
) -> FastAPI:
    """Create the service. Tests pass ``dependencies``, a factory that receives the app's
    metrics; otherwise Redis, PostgreSQL, Kafka and the HTTP clients are built at start-up."""
    settings = settings or Settings.from_env()
    app = create_app(service_name="bid", version=VERSION, description="ZeoAuction Bid Processing.")
    install_auth(app, jwt_settings)
    app.state.alias_secret = settings.alias_secret
    metrics = BidMetrics(app.state.metrics)

    def attach(deps: BidDependencies) -> None:
        app.state.bid_service = deps.service
        app.state.bid_repository = deps.bids

    if dependencies is not None:
        attach(dependencies(metrics))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if dependencies is not None:
            yield
            return
        redis = create_redis(settings.redis_url)
        pool = await create_pool(settings.database_url)
        timeout = httpx.Timeout(settings.http_timeout_seconds)
        auction_http = httpx.AsyncClient(base_url=settings.auction_service_url, timeout=timeout)
        pricing_http = httpx.AsyncClient(base_url=settings.pricing_service_url, timeout=timeout)
        if settings.publisher == "kafka":
            publisher = KafkaBidEventPublisher.connect(settings.kafka_bootstrap_servers)
            await publisher.start()
            app.state.readiness.add_check("kafka", publisher.ready)
        else:
            publisher = InMemoryBidEventPublisher()
        pricing: PricingClient = (
            HttpPricingClient(pricing_http, _breaker("pricing", settings), redis)
            if settings.pricing_mode == "http"
            else StubPricingClient()
        )
        bids = PostgresBidRepository(pool)
        service = BidService(
            auctions=AuctionStateClient(
                auction_http, _breaker("auction-state", settings),
                cache_seconds=settings.state_cache_seconds,
            ),
            pricing=pricing,
            funds=StubFunds(settings.stub_funds_limit),
            prices=RedisPriceBuffer(redis),
            publisher=publisher,
            idempotency=IdempotencyGuard(redis, settings.idempotency_ttl_seconds),
            bids=bids,
            metrics=metrics,
            max_resolution_attempts=settings.max_resolution_attempts,
        )
        attach(BidDependencies(service=service, bids=bids))
        app.state.readiness.add_check("redis", redis_check(redis))
        app.state.readiness.add_check("postgres", postgres_check(pool))
        try:
            yield
        finally:
            if isinstance(publisher, KafkaBidEventPublisher):
                await publisher.stop()
            await auction_http.aclose()
            await pricing_http.aclose()
            await pool.close()
            await redis.aclose()

    app.router.lifespan_context = lifespan
    app.state.bid_metrics = metrics
    app.include_router(router)
    return app


app = build_app()
