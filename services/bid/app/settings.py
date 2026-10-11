"""Bid Processing settings, read once at start-up (names match docker-compose.yml)."""

from dataclasses import dataclass
from decimal import Decimal

from zeo_common import parse_money
from zeo_common.settings import env_float, env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str
    auction_service_url: str
    pricing_service_url: str
    # "http" calls the Pricing Engine (CT-3, Compose and Render); "stub" uses the tier table.
    pricing_mode: str
    # "kafka" in Compose and on Render; "memory" for local runs without a broker.
    publisher: str
    # Stub funds check (FR-BID-2) until Payment exposes a funds/hold API.
    stub_funds_limit: Decimal
    idempotency_ttl_seconds: int
    http_timeout_seconds: float
    breaker_failures: int
    breaker_window_seconds: float
    breaker_reset_seconds: float
    state_cache_seconds: float
    max_resolution_attempts: int
    # Keys the per-auction bidder pseudonym; LOCAL DEVELOPMENT default only.
    alias_secret: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://bid_svc:bid_dev_pw@localhost:5432/zeoauction"
            ),
            redis_url=env_str("REDIS_URL", "redis://localhost:6379/0"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            auction_service_url=env_str("AUCTION_SERVICE_URL", "http://localhost:8003"),
            pricing_service_url=env_str("PRICING_SERVICE_URL", "http://localhost:8005"),
            pricing_mode=env_str("PRICING_MODE", "stub"),
            publisher=env_str("BID_PUBLISHER", "kafka"),
            stub_funds_limit=parse_money(env_str("STUB_FUNDS_LIMIT", "100000.00")),
            idempotency_ttl_seconds=env_int("IDEMPOTENCY_TTL_SECONDS", 24 * 60 * 60),
            http_timeout_seconds=env_float("DEPENDENCY_TIMEOUT_SECONDS", 0.5),
            breaker_failures=env_int("BREAKER_FAILURES", 5),
            breaker_window_seconds=env_float("BREAKER_WINDOW_SECONDS", 10.0),
            breaker_reset_seconds=env_float("BREAKER_RESET_SECONDS", 5.0),
            state_cache_seconds=env_float("STATE_CACHE_SECONDS", 2.0),
            max_resolution_attempts=env_int("MAX_RESOLUTION_ATTEMPTS", 5),
            alias_secret=env_str("BIDDER_ALIAS_SECRET", "zeo-dev-alias-secret"),
        )
