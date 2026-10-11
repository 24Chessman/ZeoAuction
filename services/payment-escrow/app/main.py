"""Payment, Fees & Escrow — see services/payment-escrow/README.md."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from app.adapters.kafka_producer import (
    InMemorySettlementEventPublisher,
    KafkaSettlementEventPublisher,
    SettlementEventPublisher,
)
from app.adapters.repository import (
    InMemoryPaymentRepository,
    PaymentRepository,
    PostgresPaymentRepository,
)
from app.api import router
from app.payment_port.mock_adapter import MockPaymentAdapter
from app.payment_port.port import PaymentPort
from app.payment_port.razorpay_adapter import RazorpayAdapter
from app.service import PaymentMetrics, PaymentService
from app.settings import Settings
from app.worker import SettlementWorker
from zeo_common import create_app
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check

VERSION = "0.4.0"


def build_port(settings: Settings) -> PaymentPort:
    if settings.payment_adapter == "razorpay":
        account = settings.razorpay_linked_account or None
        return RazorpayAdapter(
            key_id=settings.razorpay_key_id, key_secret=settings.razorpay_key_secret,
            webhook_secret=settings.razorpay_webhook_secret,
            linked_account_for=lambda _seller: account,
        )
    return MockPaymentAdapter()


def build_app(
    settings: Settings | None = None,
    repository: PaymentRepository | None = None,
    *,
    port: PaymentPort | None = None,
    publisher: SettlementEventPublisher | None = None,
    jwt_settings: JwtSettings | None = None,
) -> FastAPI:
    """Create the service. Tests pass ``repository``; otherwise it is built at start-up."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="payment-escrow",
        version=VERSION,
        description="ZeoAuction Payment, Fees & Escrow. Test mode only: escrow is a simulation.",
    )
    install_auth(app, jwt_settings)
    app.state.internal_token = settings.internal_token
    metrics = PaymentMetrics(app.state.metrics)
    payment_port = port or build_port(settings)
    window = timedelta(hours=settings.payment_window_hours)

    def attach(repo: PaymentRepository, events: SettlementEventPublisher) -> PaymentService:
        service = PaymentService(repo, payment_port, events, metrics, payment_window=window)
        app.state.payment_service = service
        return service

    attach(repository or InMemoryPaymentRepository(),
           publisher or InMemorySettlementEventPublisher())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs infra
        if repository is not None or settings.repository != "postgres":
            yield
            return
        pool = await create_pool(settings.database_url)
        app.state.readiness.add_check("postgres", postgres_check(pool))
        events: SettlementEventPublisher = publisher or InMemorySettlementEventPublisher()
        if publisher is None and settings.publisher == "kafka":
            kafka = KafkaSettlementEventPublisher.connect(settings.kafka_bootstrap_servers)
            await kafka.start()
            app.state.readiness.add_check("kafka", kafka.ready)
            events = kafka
        service = attach(PostgresPaymentRepository(pool), events)
        worker = SettlementWorker(service, settings.worker_interval_seconds)
        if settings.run_settlement_worker:
            worker.start()
        try:
            yield
        finally:
            await worker.stop()
            if isinstance(events, KafkaSettlementEventPublisher):
                await events.stop()
            if isinstance(payment_port, RazorpayAdapter):
                await payment_port.aclose()
            await pool.close()

    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


app = build_app()
