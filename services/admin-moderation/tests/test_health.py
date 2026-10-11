from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["service"] == "admin-moderation"


def test_readyz():
    assert client.get("/readyz").status_code == 200


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'service="admin-moderation"' in response.text


def test_errors_use_the_envelope():
    body = client.get("/api/v1/unknown-route").json()
    assert body["code"] == "NOT_FOUND"
    assert "request_id" in body
