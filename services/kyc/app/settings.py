"""KYC settings, read once at start-up (names match docker-compose.yml)."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from zeo_common.settings import env_int, env_str

SERVICE_ROOT = Path(__file__).resolve().parent.parent
# UIDAI's Secure QR signing certificate ("DS Unique Identification Authority of India 06",
# valid 2026-02-03 to 2029-02-03, SHA-256 E0:30:4B:9E:...:04:F2:77:DF), published on
# https://uidai.gov.in/en/data-and-download as uidai_offline_publickey_2026.cer
# (copy taken 2026-10-21).
UIDAI_CERTIFICATE = Path(__file__).resolve().parent / "certs" / "uidai_offline_publickey_2026.cer"


def _max_age(hours: int) -> timedelta | None:
    return timedelta(hours=hours) if hours > 0 else None


def _paths(value: str) -> tuple[Path, ...]:
    return tuple(Path(p.strip()) for p in value.split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    # "postgres" in Compose and on Render; "memory" for local runs without a database.
    repository: str
    # "s3" in Compose and on Render; "memory" keeps documents in process (tests, demos).
    storage: str
    signed_url_ttl_seconds: int
    # Retention ADR pending (FR-DOC-4); the purge job (Plan 6) honours purge_after.
    retention_days: int
    # Certificates whose signatures on the Secure QR are accepted. UIDAI's by default; a
    # synthetic dev certificate (scripts/synthetic_qr.py) is added for demos only.
    trusted_certificates: tuple[Path, ...] = (UIDAI_CERTIFICATE,)
    # How old the QR may be. None (KYC_AADHAAR_MAX_AGE_HOURS=0, the default): no limit, as
    # the QR on a printed letter or PVC card dates from when it was printed.
    aadhaar_max_age: timedelta | None = None
    max_frame_bytes: int = 0  # legacy compatibility; live face capture is removed

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
            retention_days=env_int("KYC_RETENTION_DAYS", 365),
            trusted_certificates=(UIDAI_CERTIFICATE,)
            + _paths(env_str("KYC_EXTRA_TRUSTED_CERTS", "")),
            aadhaar_max_age=_max_age(env_int("KYC_AADHAAR_MAX_AGE_HOURS", 0)),
        )
