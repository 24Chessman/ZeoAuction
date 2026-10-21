"""Fraud Detection (worker) — see services/fraud-detector/README.md."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from app.adapters.alert_producer import InMemoryAlertProducer, KafkaAlertProducer
from app.adapters.alert_repo import InMemoryAlertRepository, PostgresAlertRepository
from app.alerts import AlertMetrics, AlertProducer, AlertPublisher, AlertRepository
from app.consumer import ConsumerMetrics, FraudConsumer
from app.features import FeatureExtractor
from app.pipeline import ScoringPipeline
from app.scorer import ShillDetector, ShillScorer
from app.settings import Settings
from app.windows import AuctionWindows
from zeo_common import create_app
from zeo_common.db import create_pool, postgres_check

VERSION = "0.3.0"


def build_app(settings: Settings | None = None) -> FastAPI:
    """Worker: the HTTP surface is health and metrics only; the consumer runs alongside."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="fraud-detector",
        version=VERSION,
        description="ZeoAuction Fraud Detection (worker).",
    )
    metrics = ConsumerMetrics(app.state.metrics)
    alert_metrics = AlertMetrics(app.state.metrics)
    # Validated at start-up, so a bad FRAUD_ALERT_THRESHOLD fails fast.
    scorer = ShillScorer(threshold=settings.alert_threshold)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs Kafka
        if not settings.consume_bids:
            yield
            return
        pool = None
        repository: AlertRepository = InMemoryAlertRepository()
        if settings.alert_repository == "postgres":
            pool = await create_pool(settings.database_url)
            app.state.readiness.add_check("postgres", postgres_check(pool))
            repository = PostgresAlertRepository(pool)
        producer: AlertProducer = InMemoryAlertProducer()
        if settings.alert_publisher == "kafka":
            kafka = KafkaAlertProducer.connect(settings.kafka_bootstrap_servers)
            await kafka.start()
            app.state.readiness.add_check("kafka", kafka.ready)
            producer = kafka
        pipeline = ScoringPipeline(
            ShillDetector(scorer), AlertPublisher(producer, repository, metrics=alert_metrics))
        consumer = FraudConsumer.connect(
            settings.kafka_bootstrap_servers,
            windows=AuctionWindows(settings.window_events,
                                   timedelta(minutes=settings.close_grace_minutes)),
            extractor=FeatureExtractor(),
            metrics=metrics,
            on_features=pipeline,
            on_expire=pipeline.forget_auction,
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
            if isinstance(producer, KafkaAlertProducer):
                await producer.stop()
            if pool is not None:
                await pool.close()

    app.router.lifespan_context = lifespan
    return app


async def _running(task: asyncio.Task) -> bool:  # pragma: no cover - needs Kafka
    return not task.done()


app = build_app()
