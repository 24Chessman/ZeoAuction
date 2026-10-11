from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from zeo_common import ApiError, create_app
from zeo_common.auth import (
    AdminPrincipal,
    CurrentPrincipal,
    JwtSettings,
    decode_access_token,
    encode_access_token,
    install_auth,
)

SETTINGS = JwtSettings(secret="test-secret-at-least-32-bytes-long!!")


def token(**overrides):
    claims = {
        "user_id": uuid4(),
        "role": "USER",
        "kyc_status": "VERIFIED",
        "suspended": False,
    } | overrides
    return encode_access_token(SETTINGS, **claims)


def test_round_trip_carries_the_adr5_claims():
    user_id = uuid4()
    principal = decode_access_token(
        SETTINGS, token(user_id=user_id, kyc_status="NOT_SUBMITTED", suspended=True)
    )
    assert principal.user_id == user_id
    assert principal.role == "USER"
    assert principal.kyc_status == "NOT_SUBMITTED"
    assert principal.suspended is True
    assert principal.is_admin is False


def test_access_token_lives_fifteen_minutes():
    issued = datetime.now(UTC)
    claims = jwt.decode(
        token(now=issued), SETTINGS.secret, algorithms=["HS256"], audience="zeoauction"
    )
    assert claims["exp"] - claims["iat"] == 15 * 60


def test_expired_token_is_rejected():
    stale = token(now=datetime.now(UTC) - timedelta(minutes=16))
    with pytest.raises(ApiError) as caught:
        decode_access_token(SETTINGS, stale)
    assert caught.value.code == "UNAUTHENTICATED"


def test_token_signed_with_another_secret_is_rejected():
    other = encode_access_token(
        JwtSettings(secret="another-secret-of-sufficient-length!"),
        user_id=uuid4(), role="USER", kyc_status="VERIFIED", suspended=False,
    )
    with pytest.raises(ApiError):
        decode_access_token(SETTINGS, other)


@pytest.mark.parametrize(
    "tamper",
    [
        {"typ": "refresh"},
        {"role": "SUPERUSER"},
        {"kyc_status": "MAYBE"},
        {"suspended": "no"},
        {"sub": "not-a-uuid"},
        {"aud": "someone-else"},
    ],
)
def test_malformed_claims_are_rejected(tamper):
    now = datetime.now(UTC)
    claims = {
        "iss": SETTINGS.issuer, "aud": SETTINGS.audience, "sub": str(uuid4()), "role": "USER",
        "kyc_status": "VERIFIED", "suspended": False, "typ": "access",
        "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()),
    } | tamper
    forged = jwt.encode(claims, SETTINGS.secret, algorithm="HS256")
    with pytest.raises(ApiError):
        decode_access_token(SETTINGS, forged)


def test_alg_none_is_rejected():
    claims = {"sub": str(uuid4()), "role": "ADMIN", "typ": "access"}
    forged = jwt.encode(claims, key=None, algorithm="none")
    with pytest.raises(ApiError):
        decode_access_token(SETTINGS, forged)


@pytest.fixture
def client():
    app = create_app("auth-test")
    install_auth(app, SETTINGS)

    @app.get("/api/v1/me")
    async def me(principal: CurrentPrincipal):
        return {"sub": str(principal.user_id)}

    @app.get("/api/v1/admin")
    async def admin(principal: AdminPrincipal):
        return {"ok": True}

    return TestClient(app)


def test_dependency_accepts_a_bearer_token(client):
    user_id = uuid4()
    headers = {"Authorization": f"Bearer {token(user_id=user_id)}"}
    response = client.get("/api/v1/me", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"sub": str(user_id)}


@pytest.mark.parametrize("header", [None, "Bearer", "Basic abc", "Bearer not.a.jwt"])
def test_dependency_rejects_missing_or_bad_tokens(client, header):
    headers = {"Authorization": header} if header else {}
    response = client.get("/api/v1/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_admin_gate(client):
    user = {"Authorization": f"Bearer {token()}"}
    admin = {"Authorization": f"Bearer {token(role='ADMIN')}"}
    assert client.get("/api/v1/admin", headers=user).status_code == 403
    assert client.get("/api/v1/admin", headers=admin).status_code == 200


def test_route_without_install_auth_fails_loudly():
    app = create_app("misconfigured")

    @app.get("/api/v1/me")
    async def me(principal: CurrentPrincipal):
        return {}

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/me", headers={"Authorization": f"Bearer {token()}"}
    )
    assert response.status_code == 500


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "from-env-secret-of-sufficient-length")
    monkeypatch.setenv("JWT_ACCESS_TTL_SECONDS", "60")
    settings = JwtSettings.from_env()
    assert settings.secret == "from-env-secret-of-sufficient-length"
    assert settings.access_ttl_seconds == 60


def test_settings_fall_back_to_the_dev_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    assert JwtSettings.from_env().secret.startswith("zeo-dev")
