"""WebSocket Gateway settings, read once at start-up (names match docker-compose.yml)."""

import socket
from dataclasses import dataclass

from zeo_common.settings import env_bool, env_float, env_int, env_str


@dataclass(frozen=True)
class Settings:
    redis_url: str
    kafka_bootstrap_servers: str
    # Each instance needs its own group so it receives every event for its own sockets.
    consumer_group: str
    consume: bool = False
    use_redis: bool = False
    max_connections_per_user: int = 5
    max_subscriptions: int = 50
    max_messages_per_second: int = 20
    idle_timeout_seconds: float = 75.0
    outbox_limit: int = 256

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            redis_url=env_str("REDIS_URL", "redis://localhost:6379/0"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            consumer_group=env_str("WS_CONSUMER_GROUP", f"ws-gateway-{socket.gethostname()}"),
            consume=env_bool("WS_CONSUME_EVENTS", True),
            use_redis=env_bool("WS_USE_REDIS", True),
            max_connections_per_user=env_int("WS_MAX_CONNECTIONS_PER_USER", 5),
            max_subscriptions=env_int("WS_MAX_SUBSCRIPTIONS", 50),
            max_messages_per_second=env_int("WS_MAX_MESSAGES_PER_SECOND", 20),
            idle_timeout_seconds=env_float("WS_IDLE_TIMEOUT_SECONDS", 75.0),
            outbox_limit=env_int("WS_OUTBOX_LIMIT", 256),
        )
