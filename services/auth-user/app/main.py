"""Auth & User Service — see services/auth-user/README.md."""

import logging
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
from app.domain.email_tokens import InMemoryEmailTokenStore
from app.domain.otp import OtpStore
from app.domain.refresh_tokens import (
    InMemoryRefreshTokenStore,
    RefreshTokens,
    RefreshTokenStore,
)
from app.settings import Settings
from zeo_common import create_app
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check

logger = logging.getLogger("auth_svc.main")


def build_app(
    settings: Settings | None = None,
    *,
    users: UserRepository | None = None,
    token_store: RefreshTokenStore | None = None,
    jwt_settings: JwtSettings | None = None,
    otp_store: OtpStore | None = None,
    email_token_store: InMemoryEmailTokenStore | None = None,
) -> FastAPI:
    """Create the service. Tests pass in-memory stores; otherwise PostgreSQL is used."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="auth-user", version="0.2.0", description="ZeoAuction Auth & User Service."
    )
    install_auth(app, jwt_settings)
    app.state.settings = settings
    app.state.otp_store = otp_store or OtpStore()
    app.state.email_tokens = email_token_store or InMemoryEmailTokenStore()
    ttl = timedelta(days=settings.refresh_ttl_days)

    in_memory = users is not None
    logger.info(
        "[AUTH-USER] Service configuration: in_memory=%s, refresh_ttl=%dd, gmail_user=%s, smtp_host=%s",
        in_memory,
        settings.refresh_ttl_days,
        settings.gmail_user or "disabled",
        settings.smtp_host,
    )

    def attach(user_repo: UserRepository, store: RefreshTokenStore) -> None:
        app.state.users = user_repo
        app.state.refresh_tokens = RefreshTokens(store, ttl)

    attach(users or InMemoryUserRepository(), token_store or InMemoryRefreshTokenStore())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if in_memory:
            logger.info("[AUTH-USER] Running with in-memory stores (tests mode)")
            yield
            return
        logger.info("[AUTH-USER] Initializing database pool for schema '%s'...", settings.database_schema)
        pool = await create_pool(settings.database_url, schema=settings.database_schema)
        attach(PostgresUserRepository(pool), PostgresRefreshTokenStore(pool))
        app.state.readiness.add_check("postgres", postgres_check(pool))
        logger.info("[AUTH-USER] Auth & User Service ready to accept requests.")
        try:
            yield
        finally:
            logger.info("[AUTH-USER] Shutting down service and closing database pool...")
            await pool.close()
            logger.info("[AUTH-USER] Database pool closed.")

    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


app = build_app()
