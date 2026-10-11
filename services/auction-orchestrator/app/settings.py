"""Auction Orchestration settings, read once at start-up."""

from dataclasses import dataclass

from zeo_common.settings import env_bool, env_float, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    # "postgres" in Compose and on Render; "memory" for local experiments without a database.
    repository: str
    redis_url: str
    kafka_bootstrap_servers: str
    # "kafka" in Compose and on Render; "memory" for local runs without a broker.
    publisher: str = "memory"
    # Consume bid.events for anti-snipe and the leader (needs Kafka).
    consume_bids: bool = False
    # Check the token_version published by KYC on the listing gate (needs Redis).
    check_token_freshness: bool = False
    # Run the lifecycle timer (A2 open, A5 close, A6 drained) in this process.
    run_timer: bool = False
    timer_interval_seconds: float = 1.0
    # A6 waits this long after A5 for in-flight accepted bids to arrive on bid.events.
    drain_grace_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str(
                "DATABASE_URL", "postgresql://auction_svc:auction_dev_pw@localhost:5432/zeoauction"
            ),
            repository=env_str("AUCTION_REPOSITORY", "postgres"),
            redis_url=env_str("REDIS_URL", "redis://localhost:6379/0"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            publisher=env_str("AUCTION_PUBLISHER", "kafka"),
            consume_bids=env_bool("CONSUME_BID_EVENTS", True),
            check_token_freshness=env_bool("CHECK_TOKEN_FRESHNESS", True),
            run_timer=env_bool("RUN_LIFECYCLE_TIMER", True),
            timer_interval_seconds=env_float("LIFECYCLE_TIMER_INTERVAL_SECONDS", 1.0),
            drain_grace_seconds=env_float("DRAIN_GRACE_SECONDS", 5.0),
        )
