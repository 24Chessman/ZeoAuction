from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.user_repo import InMemoryUserRepository
from app.domain.refresh_tokens import InMemoryRefreshTokenStore
from app.domain.users import User
from app.main import build_app
from app.settings import Settings
from zeo_common.auth import JwtSettings, decode_access_token

JWT = JwtSettings(secret="auth-service-test-secret-32-bytes!")
PASSWORD = "correct-horse-42"


def settings(**overrides) -> Settings:
    base = Settings(database_url="unused", refresh_ttl_days=14, accept_seed_password=False,
                    seed_password="zeo-dev-password")
    return replace(base, **overrides)


@pytest.fixture
def users():
    return InMemoryUserRepository()


@pytest.fixture
def client(users):
    app = build_app(settings(), users=users, token_store=InMemoryRefreshTokenStore(),
                    jwt_settings=JWT)
    return TestClient(app)


def register(client, email="buyer@example.com", password=PASSWORD, name="Buyer One"):
    return client.post("/api/v1/auth/register",
                       json={"email": email, "password": password, "display_name": name})


def login(client, email="buyer@example.com", password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_register_returns_a_plain_user_profile(client):
    response = register(client, email="  Buyer@Example.COM ")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "buyer@example.com"
    assert (body["role"], body["kyc_status"], body["suspended"]) == ("USER", "NOT_SUBMITTED", False)
    assert "password" not in str(body)


def test_register_cannot_choose_role_or_kyc(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "a@example.com", "password": PASSWORD, "display_name": "A",
        "role": "ADMIN", "kyc_status": "VERIFIED"})
    assert response.json()["role"] == "USER"
    assert response.json()["kyc_status"] == "NOT_SUBMITTED"


def test_duplicate_email_is_a_conflict_regardless_of_case(client):
    register(client)
    response = register(client, email="BUYER@example.com")
    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("email", {"email": "not-an-email"}),
        ("password", {"password": "short1"}),
        ("password", {"password": "onlyletterslong"}),
        ("display_name", {"name": "   "}),
    ],
)
def test_registration_rules(client, field, kwargs):
    response = register(client, **kwargs)
    assert response.status_code == 422
    assert response.json()["details"] == {"field": field}


def test_login_issues_a_15_minute_access_token_with_the_adr5_claims(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 900
    principal = decode_access_token(JWT, tokens["access_token"])
    assert str(principal.user_id) == tokens["user"]["user_id"]
    assert (principal.role, principal.kyc_status, principal.suspended) == (
        "USER", "NOT_SUBMITTED", False)


@pytest.mark.parametrize(
    ("email", "password"),
    [("buyer@example.com", "wrong-password-1"), ("nobody@example.com", PASSWORD)],
)
def test_wrong_password_and_unknown_email_look_the_same(client, email, password):
    register(client)
    response = login(client, email=email, password=password)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert response.json()["message"] == "Email or password is incorrect"


def test_register_login_refresh_me_end_to_end(client):
    register(client)
    tokens = login(client).json()
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    me = client.get("/api/v1/users/me", headers=bearer(new_tokens))
    assert me.status_code == 200
    assert me.json()["display_name"] == "Buyer One"


def test_replayed_refresh_token_is_detected_and_ends_every_session(client):
    register(client)
    stolen = login(client).json()["refresh_token"]
    legitimate = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen}).json()
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_TOKEN_REUSED"
    after = client.post("/api/v1/auth/refresh",
                        json={"refresh_token": legitimate["refresh_token"]})
    assert after.status_code == 401


def test_refresh_reflects_changed_claims(client, users):
    register(client)
    tokens = login(client).json()
    user = next(iter(users.users.values()))
    users.users[user.id] = replace(user, kyc_status="VERIFIED", suspended=True)
    refreshed = client.post("/api/v1/auth/refresh",
                            json={"refresh_token": tokens["refresh_token"]}).json()
    principal = decode_access_token(JWT, refreshed["access_token"])
    assert (principal.kyc_status, principal.suspended) == ("VERIFIED", True)


def test_unknown_refresh_token_is_invalid(client):
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "x" * 43})
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_INVALID"


def test_logout_revokes_the_session(client):
    register(client)
    tokens = login(client).json()
    assert client.post("/api/v1/auth/logout",
                       json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


def test_logout_of_an_unknown_token_is_harmless(client):
    assert client.post("/api/v1/auth/logout",
                       json={"refresh_token": "y" * 43}).status_code == 204


def test_me_requires_a_token(client):
    assert client.get("/api/v1/users/me").status_code == 401


def test_patch_me_updates_only_the_display_name(client):
    register(client)
    tokens = login(client).json()
    response = client.patch("/api/v1/users/me", headers=bearer(tokens),
                            json={"display_name": "  New   Name ", "role": "ADMIN"})
    assert response.status_code == 200
    assert (response.json()["display_name"], response.json()["role"]) == ("New Name", "USER")


def test_patch_me_validates(client):
    register(client)
    tokens = login(client).json()
    response = client.patch("/api/v1/users/me", headers=bearer(tokens), json={"display_name": ""})
    assert response.status_code == 422


def test_me_for_a_deleted_account_is_404(client, users):
    register(client)
    tokens = login(client).json()
    users.users.clear()
    assert client.get("/api/v1/users/me", headers=bearer(tokens)).status_code == 404


def seeded_user(users):
    now = datetime.now(UTC)
    user = User(id=uuid4(), email="seller@zeo.local", password_hash="!seed",
                display_name="Verified Seller", role="USER", kyc_status="VERIFIED",
                suspended=False, token_version=1, created_at=now, updated_at=now)
    users.users[user.id] = user
    return user


def test_seed_accounts_log_in_with_the_dev_password_only_when_enabled(users):
    user = seeded_user(users)
    disabled = TestClient(build_app(settings(), users=users, jwt_settings=JWT))
    assert login(disabled, "seller@zeo.local", "zeo-dev-password").status_code == 401

    enabled = TestClient(build_app(settings(accept_seed_password=True), users=users,
                                   jwt_settings=JWT))
    assert login(enabled, "seller@zeo.local", "wrong-password-1").status_code == 401
    response = login(enabled, "seller@zeo.local", "zeo-dev-password")
    assert response.status_code == 200
    assert response.json()["user"]["kyc_status"] == "VERIFIED"
    assert users.users[user.id].password_hash.startswith("scrypt$")
    # After re-hashing, the account works even with the dev switch off.
    assert login(disabled, "seller@zeo.local", "zeo-dev-password").status_code == 200
