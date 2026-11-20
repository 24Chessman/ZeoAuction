"""Photo evidence uploads are byte-validated and kept in the private evidence store."""

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.adapters.dispute_repo import InMemoryDisputeRepository
from app.adapters.payment_client import InMemoryPaymentClient, OrderInfo
from app.main import build_app
from tests.support import BUYER, JWT, NOW, SELLER, SETTINGS, bearer
from zeo_common.storage import InMemoryObjectStore


def test_buyer_can_upload_validated_photo_evidence():
    repo = InMemoryDisputeRepository()
    payment = InMemoryPaymentClient()
    store = InMemoryObjectStore("dispute-evidence")
    app = build_app(SETTINGS, repo, payment_client=payment, evidence_store=store, jwt_settings=JWT, clock=lambda: NOW)
    client = TestClient(app)
    order_id = uuid4()
    payment.orders[order_id] = OrderInfo(order_id, uuid4(), BUYER, SELLER, "SHIPPED", NOW + timedelta(days=2))

    created = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "DAMAGED_IN_TRANSIT", "description": "The screen arrived cracked"},
        headers=bearer(),
    )
    assert created.status_code == 201
    dispute_id = created.json()["id"]

    uploaded = client.post(
        f"/api/v1/disputes/{dispute_id}/evidence/upload",
        files={"photo": ("damage.png", b"\x89PNG\r\n\x1a\nphoto-bytes", "image/png")},
        headers=bearer(),
    )
    assert uploaded.status_code == 201
    key = uploaded.json()["object_key"]
    assert uploaded.json()["kind"] == "PHOTO"
    assert key in store.objects


def test_photo_upload_rejects_non_image_bytes():
    repo = InMemoryDisputeRepository()
    payment = InMemoryPaymentClient()
    app = build_app(SETTINGS, repo, payment_client=payment, evidence_store=InMemoryObjectStore(), jwt_settings=JWT, clock=lambda: NOW)
    client = TestClient(app)
    order_id = uuid4()
    payment.orders[order_id] = OrderInfo(order_id, uuid4(), BUYER, SELLER, "SHIPPED", NOW + timedelta(days=2))
    dispute_id = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "OTHER", "description": "Need help"}, headers=bearer(),
    ).json()["id"]

    rejected = client.post(
        f"/api/v1/disputes/{dispute_id}/evidence/upload",
        files={"photo": ("not-a-photo.jpg", b"not an image", "image/jpeg")}, headers=bearer(),
    )
    assert rejected.status_code == 422
