"""Environment-driven settings shared by every service.

Each service declares its own frozen dataclass of settings and builds it with the ``env_*``
readers below, so configuration is read once at start-up and passed around explicitly.
Values that differ per environment come from Compose locally and from Render environment
groups when hosted; nothing secret is committed (``docs/engineering-conventions.md``).
"""

import os
from dataclasses import dataclass


class SettingsError(ValueError):
    pass


def env_str(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            raise SettingsError(f"environment variable {name} is required")
        return default
    return value


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer, got {raw!r}") from exc


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from exc


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise SettingsError(f"{name} must be a boolean, got {raw!r}")


@dataclass(frozen=True)
class InfraSettings:
    """Connection strings every stateful service reads (names match docker-compose.yml)."""

    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str

    @classmethod
    def from_env(cls) -> "InfraSettings":
        return cls(
            database_url=env_str("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/zeoauction"),
            redis_url=env_str("REDIS_URL", "redis://localhost:6379/0"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
        )
