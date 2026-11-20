"""KYC & Seller Verification — see services/kyc/README.md."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import admin_api, api
from app.adapters.document_store import DocumentStore
from app.adapters.kyc_repo import InMemoryKycRepository, KycRepository, PostgresKycRepository
from app.adapters.qr_reader import QrReader, ZxingQrReader
from app.adapters.user_mirror import TokenRefreshAnnouncer
from app.domain.aadhaar import TrustedKey, load_trusted_key
from app.service import KycService
from app.settings import Settings
from zeo_common import create_app
from zeo_common.auth import JwtSettings, install_auth
from zeo_common.db import create_pool, postgres_check
from zeo_common.gateway import RedisTokenVersions, TokenVersionPublisher
from zeo_common.redis import create_redis, redis_check
from zeo_common.settings import env_str
from zeo_common.storage import InMemoryObjectStore, ObjectStore, S3ObjectStore, StorageSettings

VERSION = "0.5.0"
BUCKET = "kyc-documents"


def build_app(
    settings: Settings | None = None,
    *,
    repository: KycRepository | None = None,
    store: ObjectStore | None = None,
    token_versions: TokenVersionPublisher | None = None,
    jwt_settings: JwtSettings | None = None,
    qr_reader: QrReader | None = None,
    trusted_keys: list[TrustedKey] | None = None,
) -> FastAPI:
    """Create the service. Tests pass the adapters; otherwise they are built at start-up."""
    settings = settings or Settings.from_env()
    app = create_app(
        service_name="kyc", version=VERSION, description="ZeoAuction KYC & Seller Verification."
    )
    install_auth(app, jwt_settings)
    # Fail at start-up, not on the first seller, if the UIDAI certificate is missing.
    keys = trusted_keys if trusted_keys is not None else [
        load_trusted_key(path.read_bytes()) for path in settings.trusted_certificates
    ]

    def attach(repo: KycRepository, objects: ObjectStore,
               publisher: TokenVersionPublisher | None) -> None:
        app.state.kyc_service = KycService(
            repo,
            DocumentStore(objects, settings.signed_url_ttl_seconds),
            TokenRefreshAnnouncer(publisher),
            qr_reader or ZxingQrReader(),
            trusted_keys=keys,
            aadhaar_max_age=settings.aadhaar_max_age,
            retention_days=settings.retention_days,
        )

    injected = repository is not None or settings.repository == "memory"
    if injected:
        attach(repository or InMemoryKycRepository(), store or InMemoryObjectStore(BUCKET),
               token_versions)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - needs infra
        if injected:
            yield
            return
        pool = await create_pool(settings.database_url)
        redis = create_redis(settings.redis_url)
        objects: ObjectStore
        if store is not None:
            objects = store
        elif settings.storage == "s3":
            bucket = env_str("S3_BUCKET_KYC", env_str("S3_BUCKET", BUCKET))
            objects = S3ObjectStore(StorageSettings.from_env(bucket))
        else:
            objects = InMemoryObjectStore(BUCKET)
        attach(PostgresKycRepository(pool), objects, token_versions or RedisTokenVersions(redis))
        app.state.readiness.add_check("postgres", postgres_check(pool))
        app.state.readiness.add_check("redis", redis_check(redis))
        try:
            yield
        finally:
            if isinstance(objects, S3ObjectStore):
                await objects.aclose()
            await pool.close()
            await redis.aclose()

    app.router.lifespan_context = lifespan
    app.include_router(api.router)
    app.include_router(admin_api.router)
    return app


app = build_app()
