"""Fraud Detection settings, read once at start-up (names match docker-compose.yml)."""

from dataclasses import dataclass

from zeo_common.settings import env_bool, env_int, env_str


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap_servers: str
    # Run the bid.events consumer in this process (needs Kafka).
    consume_bids: bool = False
    # Bids kept per auction window, and minutes a window outlives its auction's close.
    window_events: int = 200
    close_grace_minutes: int = 10

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            consume_bids=env_bool("CONSUME_BID_EVENTS", False),
            window_events=env_int("FRAUD_WINDOW_EVENTS", 200),
            close_grace_minutes=env_int("FRAUD_CLOSE_GRACE_MINUTES", 10),
        )
