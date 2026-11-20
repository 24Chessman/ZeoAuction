"""Dispute Management — see services/dispute/README.md."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app import admin_api, api
from app.adapters.dispute_repo import (
    DisputeRepository,
    InMemoryDisputeRepository,
    PostgresDisputeRepository,
)
from app.adapters.payment_client import (
    HttpPaymentClient,
    InMemoryPaymentClient,
    PaymentClient,
)
from app.service import DisputeService
from app.settings import Settings
from zeo_common import create_app
from zeo_common.audit import AuditWriter, InMemoryAuditWriter, PostgresAuditWriter
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check
from zeo_common.storage import InMemoryObjectStore, ObjectStore, S3ObjectStore, StorageSettings

VERSION = "0.6.0"


def build_app(
    settings: Settings | None = None,
    repository: DisputeRepository | None = None,
    *,
    payment_client: PaymentClient | None = None,
    audit_writer: AuditWriter | None = None,
    evidence_store: ObjectStore | None = None,
    jwt_settings: JwtSettings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="dispute",
        version=VERSION,
        description="ZeoAuction Dispute Management.",
    )
    install_auth(app, jwt_settings)

    def attach(
        repo: DisputeRepository,
        client: PaymentClient,
        audit: AuditWriter,
    ) -> DisputeService:
        service = DisputeService(
            repo=repo,
            payment_client=client,
            audit_writer=audit,
            clock=clock or (lambda: datetime.now(UTC)),
        )
        app.state.dispute_service = service
        return service

    injected = repository is not None or settings.repository == "memory"
    if injected:
        app.state.evidence_store = evidence_store or InMemoryObjectStore("dispute-evidence")
        attach(
            repository or InMemoryDisputeRepository(),
            payment_client or InMemoryPaymentClient(),
            audit_writer or InMemoryAuditWriter(),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover
        if injected:
            yield
            return
        pool = await create_pool(settings.database_url)
        app.state.readiness.add_check("postgres", postgres_check(pool))
        client = payment_client or HttpPaymentClient(
            settings.payment_service_url, settings.internal_token
        )
        audit = audit_writer or PostgresAuditWriter(pool)
        store = evidence_store or S3ObjectStore(
            StorageSettings.from_env("dispute-evidence", encrypted=True)
        )
        app.state.evidence_store = store
        attach(PostgresDisputeRepository(pool), client, audit)
        try:
            yield
        finally:
            close = getattr(store, "aclose", None)
            if close:
                await close()
            await pool.close()

    app.router.lifespan_context = lifespan
    app.include_router(api.router)
    app.include_router(admin_api.router)
    return app


app = build_app()
