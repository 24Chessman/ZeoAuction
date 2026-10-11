from typing import Annotated
from uuid import uuid4

import fakeredis
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from zeo_common import create_app
from zeo_common.auth import JwtSettings, Principal, encode_access_token, install_auth
from zeo_common.gateway import (
    ActivePrincipal,
    FreshPrincipal,
    InMemoryTokenVersions,
    RedisTokenVersions,
    VerifiedSeller,
    check_verified_seller,
    install_gateway,
    require_roles,
)

SETTINGS = JwtSettings(secret="test-secret-at-least-32-bytes-long!!")


def token(user_id=None, **overrides):
    claims = {
        "user_id": user_id or uuid4(),
        "role": "USER",
        "kyc_status": "VERIFIED",
        "suspended": False,
        "token_version": 1,
    } | overrides
    return encode_access_token(SETTINGS, **claims)


def build(versions=None):
    app = create_app("gateway-test")
    install_auth(app, SETTINGS)
    install_gateway(app, versions)

    @app.post("/api/v1/listings")
    async def listing(principal: VerifiedSeller) -> dict:
        return {"seller": str(principal.user_id)}

    @app.get("/api/v1/active")
    async def active(principal: ActivePrincipal) -> dict:
        return {"ok": True}

    @app.get("/api/v1/fresh")
    async def fresh(principal: FreshPrincipal) -> dict:
        return {"tv": principal.token_version}

    @app.get("/api/v1/admin-only")
    async def admin_only(
        principal: Annotated[Principal, Depends(require_roles("ADMIN"))],
    ) -> dict:
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def call(client, method, path, bearer):
    return client.request(method, path, headers={"Authorization": f"Bearer {bearer}"})


@pytest.mark.parametrize(
    "status", ["NOT_SUBMITTED", "SUBMITTED", "UNDER_REVIEW", "REJECTED", "SUSPENDED"]
)
def test_listing_gate_refuses_every_status_but_verified(status):
    response = call(build(), "POST", "/api/v1/listings", token(kyc_status=status))
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "SELLER_NOT_VERIFIED"
    assert body["details"] == {"kyc_status": status}


def test_listing_gate_admits_a_verified_seller():
    user = uuid4()
    response = call(build(), "POST", "/api/v1/listings", token(user))
    assert response.status_code == 200
    assert response.json() == {"seller": str(user)}


def test_suspension_wins_over_verification():
    response = call(build(), "POST", "/api/v1/listings", token(suspended=True))
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_SUSPENDED"
    assert call(build(), "GET", "/api/v1/active", token(suspended=True)).status_code == 403
    assert call(build(), "GET", "/api/v1/active", token()).status_code == 200


def test_no_token_is_unauthenticated():
    response = build().post("/api/v1/listings")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_a_token_older_than_the_published_version_must_be_refreshed():
    versions = InMemoryTokenVersions()
    user = uuid4()
    versions.versions[user] = 2
    client = build(versions)
    # Minted before approval: the stale claim says NOT_SUBMITTED, and the client is told to
    # refresh rather than told it is unverified.
    stale = call(client, "POST", "/api/v1/listings", token(user, kyc_status="NOT_SUBMITTED"))
    assert stale.status_code == 401
    assert stale.json()["details"] == {"reason": "TOKEN_STALE"}
    refreshed = call(client, "POST", "/api/v1/listings", token(user, token_version=2))
    assert refreshed.status_code == 200


def test_a_stale_verified_token_cannot_list_after_suspension():
    versions = InMemoryTokenVersions()
    user = uuid4()
    versions.versions[user] = 3
    response = call(build(versions), "POST", "/api/v1/listings", token(user, token_version=2))
    assert response.status_code == 401


def test_unknown_users_pass_the_freshness_check():
    response = call(build(InMemoryTokenVersions()), "GET", "/api/v1/fresh", token())
    assert response.json() == {"tv": 1}


def test_freshness_fails_closed_when_the_store_is_down():
    versions = InMemoryTokenVersions()
    versions.fail = True
    response = call(build(versions), "POST", "/api/v1/listings", token())
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"


def test_role_gate():
    client = build()
    assert call(client, "GET", "/api/v1/admin-only", token()).status_code == 403
    assert call(client, "GET", "/api/v1/admin-only", token(role="ADMIN")).status_code == 200


def test_check_verified_seller_outside_a_request():
    principal = Principal(user_id=uuid4(), role="USER", kyc_status="VERIFIED", suspended=False)
    check_verified_seller(principal)


async def test_redis_token_versions_never_move_backwards():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    versions = RedisTokenVersions(redis)
    user = uuid4()
    assert await versions.current(user) is None
    await versions.publish(user, 3)
    await versions.publish(user, 2)
    assert await versions.current(user) == 3
    assert 0 < await redis.ttl(f"tv:{user}") <= 24 * 60 * 60


async def test_in_memory_token_versions_never_move_backwards():
    versions = InMemoryTokenVersions()
    user = uuid4()
    await versions.publish(user, 4)
    await versions.publish(user, 1)
    assert await versions.current(user) == 4
