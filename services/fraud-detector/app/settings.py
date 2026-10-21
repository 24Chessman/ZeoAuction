"""Fraud Detection settings, read once at start-up (names match docker-compose.yml)."""

from dataclasses import dataclass

from app.scorer import V1_THRESHOLD
from zeo_common.settings import env_bool, env_float, env_int, env_str


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap_servers: str
    # Run the bid.events consumer in this process (needs Kafka).
    consume_bids: bool = False
    # Bids kept per auction window, and minutes a window outlives its auction's close.
    window_events: int = 200
    close_grace_minutes: int = 10
    # Score at or above which a bidder is a suspect (#53).
    alert_threshold: float = V1_THRESHOLD
    # Where alerts go: "kafka" publishes to fraud.alerts, "memory" keeps them in-process.
    alert_publisher: str = "memory"
    # "postgres" stores alerts in fraud.fraud_alerts, "memory" keeps them in-process.
    alert_repository: str = "memory"
    database_url: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            consume_bids=env_bool("CONSUME_BID_EVENTS", False),
            window_events=env_int("FRAUD_WINDOW_EVENTS", 200),
            close_grace_minutes=env_int("FRAUD_CLOSE_GRACE_MINUTES", 10),
            alert_threshold=env_float("FRAUD_ALERT_THRESHOLD", V1_THRESHOLD),
            alert_publisher=env_str("FRAUD_ALERT_PUBLISHER", "memory"),
            alert_repository=env_str("FRAUD_ALERT_REPOSITORY", "memory"),
            database_url=env_str("DATABASE_URL", ""),
        )
