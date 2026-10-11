"""Auth & User Service — see services/auth-user/README.md."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from app.adapters.user_repo import (
    InMemoryUserRepository,
    PostgresRefreshTokenStore,
    PostgresUserRepository,
    UserRepository,
)
from app.api import router
from app.domain.refresh_tokens import (
    InMemoryRefreshTokenStore,
    RefreshTokens,
    RefreshTokenStore,
)
from app.settings import Settings
from zeo_common import create_app
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check


def build_app(
    settings: Settings | None = None,
    *,
    users: UserRepository | None = None,
    token_store: RefreshTokenStore | None = None,
    jwt_settings: JwtSettings | None = None,
) -> FastAPI:
    """Create the service. Tests pass in-memory stores; otherwise PostgreSQL is used."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="auth-user", version="0.2.0", description="ZeoAuction Auth & User Service."
    )
    install_auth(app, jwt_settings)
    app.state.settings = settings
    ttl = timedelta(days=settings.refresh_ttl_days)

    def attach(user_repo: UserRepository, store: RefreshTokenStore) -> None:
        app.state.users = user_repo
        app.state.refresh_tokens = RefreshTokens(store, ttl)

    in_memory = users is not None
    attach(users or InMemoryUserRepository(), token_store or InMemoryRefreshTokenStore())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if in_memory:
            yield
            return
        pool = await create_pool(settings.database_url)
        attach(PostgresUserRepository(pool), PostgresRefreshTokenStore(pool))
        app.state.readiness.add_check("postgres", postgres_check(pool))
        try:
            yield
        finally:
            await pool.close()

    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


app = build_app()
