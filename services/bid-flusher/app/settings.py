"""Bid flusher settings, read once at start-up."""

from dataclasses import dataclass

from zeo_common.settings import env_bool, env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str
    batch_max_size: int
    batch_max_age_ms: int
    poll_interval_ms: int
    replay_on_start: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://bid_svc:bid_dev_pw@localhost:5432/zeoauction"
            ),
            redis_url=env_str("REDIS_URL", "redis://localhost:6379/0"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            batch_max_size=env_int("FLUSH_BATCH_MAX_SIZE", 500),
            batch_max_age_ms=env_int("FLUSH_BATCH_MAX_AGE_MS", 500),
            poll_interval_ms=env_int("FLUSH_POLL_INTERVAL_MS", 50),
            replay_on_start=env_bool("REPLAY_ON_START", True),
        )
