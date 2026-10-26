"""Admin & Moderation — see services/admin-moderation/README.md."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app import api
from app.adapters.admin_repo import (
    AdminRepository,
    InMemoryAdminRepository,
    PostgresAdminRepository,
)
from app.service import AdminService
from app.settings import Settings
from zeo_common import create_app
from zeo_common.audit import AuditWriter, InMemoryAuditWriter, PostgresAuditWriter
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check
from zeo_common.gateway import RedisTokenVersions, TokenVersionPublisher
from zeo_common.redis import create_redis

VERSION = "0.6.0"


def build_app(
    settings: Settings | None = None,
    repository: AdminRepository | None = None,
    *,
    audit_writer: AuditWriter | None = None,
    token_publisher: TokenVersionPublisher | None = None,
    jwt_settings: JwtSettings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="admin-moderation",
        version=VERSION,
        description="ZeoAuction Admin & Moderation.",
    )
    install_auth(app, jwt_settings)

    def attach(
        repo: AdminRepository,
        audit: AuditWriter,
        publisher: TokenVersionPublisher | None,
    ) -> AdminService:
        service = AdminService(
            repo=repo,
            audit_writer=audit,
            token_publisher=publisher,
            clock=clock or (lambda: datetime.now(UTC)),
        )
        app.state.admin_service = service
        return service

    injected = repository is not None or settings.repository == "memory"
    if injected:
        attach(
            repository or InMemoryAdminRepository(),
            audit_writer or InMemoryAuditWriter(),
            token_publisher,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover
        if injected:
            yield
            return
        pool = await create_pool(settings.database_url)
        redis = create_redis(settings.redis_url)
        app.state.readiness.add_check("postgres", postgres_check(pool))
        audit = audit_writer or PostgresAuditWriter(pool)
        publisher = token_publisher or RedisTokenVersions(redis)
        attach(PostgresAdminRepository(pool), audit, publisher)
        try:
            yield
        finally:
            await pool.close()
            await redis.aclose()

    app.router.lifespan_context = lifespan
    app.include_router(api.router)
    return app


app = build_app()
