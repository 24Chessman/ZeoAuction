import uuid

import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from zeo_common import ApiError, create_app


@pytest.fixture
def app():
    app = create_app("test-service", version="9.9.9")

    @app.get("/api/v1/boom-domain")
    async def boom_domain():
        raise ApiError(
            "BID_BELOW_INCREMENT", "Minimum next bid is 1250.00", 422, {"min": "1250.00"}
        )

    @app.get("/api/v1/boom-unhandled")
    async def boom_unhandled():
        raise RuntimeError("secret internals")

    @app.get("/api/v1/needs-int")
    async def needs_int(n: int = Query(...)):
        return {"n": n}

    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def assert_envelope(body, code):
    assert set(body) == {"code", "message", "details", "request_id"}
    assert body["code"] == code
    uuid.UUID(body["request_id"])


def test_healthz_reports_service_identity(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "test-service", "version": "9.9.9"}


def test_readyz_is_ready_with_no_checks(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_is_unready_when_a_check_fails(app, client):
    async def ok():
        return True

    async def broken():
        raise ConnectionError("db down")

    app.state.readiness.add_check("redis", ok)
    app.state.readiness.add_check("postgres", broken)

    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"] == {"redis": "ok", "postgres": "fail"}


def test_metrics_exposes_service_info(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'zeo_service_info{service="test-service",version="9.9.9"} 1.0' in response.text


def test_api_error_uses_envelope_and_status(client):
    response = client.get("/api/v1/boom-domain")
    assert response.status_code == 422
    body = response.json()
    assert_envelope(body, "BID_BELOW_INCREMENT")
    assert body["details"] == {"min": "1250.00"}


def test_validation_error_uses_envelope(client):
    response = client.get("/api/v1/needs-int", params={"n": "abc"})
    assert response.status_code == 422
    assert_envelope(response.json(), "VALIDATION_ERROR")


def test_unknown_route_uses_envelope(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert_envelope(response.json(), "NOT_FOUND")


def test_unhandled_error_hides_internals(client):
    response = client.get("/api/v1/boom-unhandled")
    assert response.status_code == 500
    body = response.json()
    assert_envelope(body, "INTERNAL_ERROR")
    assert "secret" not in body["message"]


def test_request_id_is_echoed_when_supplied(client):
    request_id = str(uuid.uuid4())
    response = client.get("/api/v1/boom-domain", headers={"X-Request-ID": request_id})
    assert response.headers["x-request-id"] == request_id
    assert response.json()["request_id"] == request_id


def test_request_id_is_minted_when_missing_or_invalid(client):
    response = client.get("/healthz", headers={"X-Request-ID": "not-a-uuid"})
    minted = response.headers["x-request-id"]
    assert minted != "not-a-uuid"
    uuid.UUID(minted)


def test_cors_is_off_unless_configured(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    client = TestClient(create_app("no-cors"))
    response = client.get("/healthz", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_configured_origins(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173")
    client = TestClient(create_app("cors"))
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Idempotency-Key",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = client.get("/healthz", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers
