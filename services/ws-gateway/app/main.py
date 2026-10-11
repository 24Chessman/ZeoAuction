"""WebSocket Gateway — see services/ws-gateway/README.md."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.connections import GatewayMetrics, Hub, Limits
from app.fanout import FanOut, FanoutConsumer, Increments
from app.rooms import RedisSnapshots, Snapshots
from app.settings import Settings
from zeo_common import create_app
from zeo_common.auth import JwtSettings
from zeo_common.redis import create_redis, redis_check

VERSION = "0.3.0"


def build_app(settings: Settings | None = None, *,
              jwt_settings: JwtSettings | None = None) -> FastAPI:
    """Create the service. Tests pass settings with ``consume`` and ``use_redis`` off and
    drive ``app.state.fanout`` directly."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="ws-gateway", version=VERSION, description="ZeoAuction WebSocket Gateway."
    )
    limits = Limits(
        max_connections_per_user=settings.max_connections_per_user,
        max_subscriptions=settings.max_subscriptions,
        max_messages_per_second=settings.max_messages_per_second,
        idle_timeout_seconds=settings.idle_timeout_seconds,
        outbox_limit=settings.outbox_limit,
    )
    hub = Hub(jwt_settings or JwtSettings.from_env(), GatewayMetrics(app.state.metrics),
              Snapshots(), limits)
    app.state.hub = hub
    app.state.fanout = FanOut(hub)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs infra
        redis = None
        if settings.use_redis:
            redis = create_redis(settings.redis_url)
            hub.snapshots.shared = RedisSnapshots(redis)
            app.state.fanout.increments = Increments(redis)
            app.state.readiness.add_check("redis", redis_check(redis))
        task = None
        if settings.consume:
            consumer = FanoutConsumer.connect(settings.kafka_bootstrap_servers,
                                              settings.consumer_group, app.state.fanout.dispatch)
            task = asyncio.create_task(consumer.run(), name="fanout-consumer")
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if redis is not None:
                await redis.aclose()

    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


app = build_app()
