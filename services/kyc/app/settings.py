"""KYC settings, read once at start-up (names match docker-compose.yml)."""

from dataclasses import dataclass

from app.domain.submission import MAX_DOCUMENT_BYTES
from zeo_common.settings import env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    # "postgres" in Compose and on Render; "memory" for local runs without a database.
    repository: str
    # "s3" in Compose and on Render; "memory" keeps documents in process (tests, demos).
    storage: str
    signed_url_ttl_seconds: int
    max_document_bytes: int
    # Retention ADR pending (FR-DOC-4); the purge job (Plan 6) honours purge_after.
    retention_days: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://kyc_svc:kyc_dev_pw@localhost:5432/zeoauction"
            ),
            redis_url=env_str("REDIS_URL", "redis://localhost:6379/0"),
            repository=env_str("KYC_REPOSITORY", "postgres"),
            storage=env_str("KYC_STORAGE", "s3"),
            signed_url_ttl_seconds=env_int("KYC_SIGNED_URL_TTL_SECONDS", 60),
            max_document_bytes=env_int("KYC_MAX_DOCUMENT_BYTES", MAX_DOCUMENT_BYTES),
            retention_days=env_int("KYC_RETENTION_DAYS", 365),
        )
