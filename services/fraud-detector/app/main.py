"""Fraud Detection (worker) — see services/fraud-detector/README.md."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from app.consumer import ConsumerMetrics, FraudConsumer
from app.features import FeatureExtractor
from app.settings import Settings
from app.windows import AuctionWindows
from zeo_common import create_app

VERSION = "0.2.0"


def build_app(settings: Settings | None = None) -> FastAPI:
    """Worker: the HTTP surface is health and metrics only; the consumer runs alongside."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="fraud-detector",
        version=VERSION,
        description="ZeoAuction Fraud Detection (worker).",
    )
    metrics = ConsumerMetrics(app.state.metrics)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs Kafka
        if not settings.consume_bids:
            yield
            return
        consumer = FraudConsumer.connect(
            settings.kafka_bootstrap_servers,
            windows=AuctionWindows(settings.window_events,
                                   timedelta(minutes=settings.close_grace_minutes)),
            extractor=FeatureExtractor(),
            metrics=metrics,
        )
        app.state.fraud_consumer = consumer
        task = asyncio.create_task(consumer.run(), name="bid-events-consumer")
        app.state.readiness.add_check("consumer", lambda: _running(task))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.router.lifespan_context = lifespan
    return app


async def _running(task: asyncio.Task) -> bool:  # pragma: no cover - needs Kafka
    return not task.done()


app = build_app()
