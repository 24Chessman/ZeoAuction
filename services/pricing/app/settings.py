"""Pricing Engine settings, read once at start-up (names match docker-compose.yml)."""

from dataclasses import dataclass

from zeo_common.settings import env_bool, env_float, env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str
    # "postgres" in Compose and on Render; "memory" for local runs without a database.
    repository: str = "memory"
    # Consume bid.events for velocity (needs Kafka).
    consume_bids: bool = False
    window_seconds: int = 60
    bucket_seconds: int = 5
    # Velocity at which the increment reaches the band's velocity_multiplier.
    saturation_bpm: float = 60.0
    hot_enter_bpm: float = 30.0
    hot_exit_bpm: float = 15.0
    # inc:{auction_id} lifetime (SDD Table 4.3).
    cache_ttl_seconds: int = 60
    flush_interval_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://pricing_svc:pricing_dev_pw@localhost:5432/zeoauction"
            ),
            redis_url=env_str("REDIS_URL", "redis://localhost:6379/0"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            repository=env_str("PRICING_REPOSITORY", "postgres"),
            consume_bids=env_bool("CONSUME_BID_EVENTS", True),
            window_seconds=env_int("PRICING_WINDOW_SECONDS", 60),
            bucket_seconds=env_int("PRICING_BUCKET_SECONDS", 5),
            saturation_bpm=env_float("PRICING_SATURATION_BPM", 60.0),
            hot_enter_bpm=env_float("HOT_ENTER_BPM", 30.0),
            hot_exit_bpm=env_float("HOT_EXIT_BPM", 15.0),
            cache_ttl_seconds=env_int("INCREMENT_CACHE_TTL_SECONDS", 60),
            flush_interval_seconds=env_float("VELOCITY_FLUSH_SECONDS", 5.0),
        )
