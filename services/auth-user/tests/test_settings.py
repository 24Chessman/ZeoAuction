"""Auth service configuration tests."""

from app.settings import Settings


def test_database_schema_defaults_to_auth(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)

    assert Settings.from_env().database_schema == "auth"


def test_database_schema_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_SCHEMA", "auth_test")

    assert Settings.from_env().database_schema == "auth_test"
