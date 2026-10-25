"""Search & Analytics — see services/search-analytics/README.md."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app import api
from app.adapters.order_client import (
    HttpOrderClient,
    InMemoryOrderClient,
    OrderClient,
)
from app.adapters.search_repo import (
    InMemorySearchRepository,
    PostgresSearchRepository,
    SearchRepository,
)
from app.service import SearchService
from app.settings import Settings
from zeo_common import create_app
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check

VERSION = "0.1.0"


def build_app(
    settings: Settings | None = None,
    repository: SearchRepository | None = None,
    order_client: OrderClient | None = None,
    *,
    jwt_settings: JwtSettings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="search-analytics",
        version=VERSION,
        description="ZeoAuction Search & Analytics.",
    )
    install_auth(app, jwt_settings)
    app.state.settings = settings

    def attach(repo: SearchRepository, client: OrderClient) -> SearchService:
        service = SearchService(
            repo=repo,
            order_client=client,
            clock=clock or (lambda: datetime.now(UTC)),
        )
        app.state.search_service = service
        return service

    injected = repository is not None or settings.repository == "memory"
    if injected:
        attach(
            repository or InMemorySearchRepository(),
            order_client or InMemoryOrderClient(),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover
        if injected:
            yield
            return
        pool = await create_pool(settings.database_url)
        app.state.readiness.add_check("postgres", postgres_check(pool))
        client = order_client or HttpOrderClient(
            settings.payment_service_url, settings.internal_service_token
        )
        attach(PostgresSearchRepository(pool), client)
        try:
            yield
        finally:
            await pool.close()

    app.router.lifespan_context = lifespan
    app.include_router(api.router)
    return app


app = build_app()
