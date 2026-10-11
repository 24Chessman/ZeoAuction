import fakeredis
import pytest

from zeo_common.db import postgres_check
from zeo_common.health import Readiness
from zeo_common.redis import redis_check
from zeo_common.settings import (
    InfraSettings,
    SettingsError,
    env_bool,
    env_float,
    env_int,
    env_str,
)


class _Connection:
    def __init__(self, healthy: bool) -> None:
        self.healthy = healthy

    async def fetchval(self, query: str) -> int:
        if not self.healthy:
            raise ConnectionError("database is down")
        return 1


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakePool:
    def __init__(self, healthy: bool = True) -> None:
        self.connection = _Connection(healthy)

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


async def test_postgres_check_passes_on_select_1():
    assert await postgres_check(FakePool())() is True


async def test_postgres_check_marks_service_unready_when_down():
    readiness = Readiness()
    readiness.add_check("postgres", postgres_check(FakePool(healthy=False)))
    assert await readiness.evaluate() == {"postgres": False}


async def test_redis_check_pings():
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    assert await redis_check(client)() is True


async def test_redis_check_marks_service_unready_when_down():
    server = fakeredis.FakeServer()
    server.connected = False
    client = fakeredis.FakeAsyncRedis(server=server)
    readiness = Readiness()
    readiness.add_check("redis", redis_check(client))
    assert await readiness.evaluate() == {"redis": False}


def test_env_readers(monkeypatch):
    monkeypatch.setenv("ZEO_INT", "42")
    monkeypatch.setenv("ZEO_FLOAT", "0.25")
    monkeypatch.setenv("ZEO_BOOL", "Yes")
    monkeypatch.setenv("ZEO_STR", "value")
    assert env_int("ZEO_INT", 1) == 42
    assert env_float("ZEO_FLOAT", 1.0) == 0.25
    assert env_bool("ZEO_BOOL", False) is True
    assert env_str("ZEO_STR") == "value"


def test_env_readers_fall_back_to_defaults(monkeypatch):
    for name in ("ZEO_INT", "ZEO_FLOAT", "ZEO_BOOL", "ZEO_STR"):
        monkeypatch.delenv(name, raising=False)
    assert env_int("ZEO_INT", 7) == 7
    assert env_float("ZEO_FLOAT", 1.5) == 1.5
    assert env_bool("ZEO_BOOL", True) is True
    assert env_str("ZEO_STR", "fallback") == "fallback"


def test_required_string_without_default_is_an_error(monkeypatch):
    monkeypatch.delenv("ZEO_REQUIRED", raising=False)
    with pytest.raises(SettingsError, match="ZEO_REQUIRED"):
        env_str("ZEO_REQUIRED")


@pytest.mark.parametrize(
    ("reader", "raw"),
    [(env_int, "ten"), (env_float, "fast"), (env_bool, "maybe")],
)
def test_malformed_values_are_rejected(monkeypatch, reader, raw):
    monkeypatch.setenv("ZEO_BAD", raw)
    with pytest.raises(SettingsError, match="ZEO_BAD"):
        reader("ZEO_BAD", None)


def test_infra_settings_read_compose_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://bid_svc:pw@postgres:5432/zeoauction")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    settings = InfraSettings.from_env()
    assert settings.database_url.startswith("postgresql://bid_svc")
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.kafka_bootstrap_servers == "kafka:9092"
