"""Tests for window-gated dispute creation (#84, AC-11, Plan 6)."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.dispute_repo import InMemoryDisputeRepository
from app.adapters.payment_client import InMemoryPaymentClient, OrderInfo
from app.main import build_app
from tests.support import (
    BUYER,
    JWT,
    NOW,
    OTHER_USER,
    SELLER,
    SETTINGS,
    bearer,
)


@pytest.fixture
def test_setup():
    repo = InMemoryDisputeRepository()
    payment = InMemoryPaymentClient()
    app = build_app(
        SETTINGS,
        repo,
        payment_client=payment,
        jwt_settings=JWT,
        clock=lambda: NOW,
    )
    client = TestClient(app)
    return client, repo, payment


def test_raise_dispute_during_open_window(test_setup):
    client, repo, payment = test_setup
    order_id = uuid4()
    payment.orders[order_id] = OrderInfo(
        order_id=order_id,
        auction_id=uuid4(),
        buyer_id=BUYER,
        seller_id=SELLER,
        state="SHIPPED",
        protection_window_ends_at=NOW + timedelta(days=5),
    )

    res = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "ITEM_NOT_RECEIVED", "description": "Package never arrived"},
        headers=bearer(BUYER),
    )
    assert res.status_code == 201
    data = res.json()
    assert data["state"] == "OPEN"
    assert data["reason_code"] == "ITEM_NOT_RECEIVED"
    assert data["opened_by"] == "BUYER"
    assert data["opened_by_user_id"] == str(BUYER)

    # Freezes escrow in Payment
    assert order_id in payment.frozen


def test_raise_dispute_refused_when_window_closed(test_setup):
    client, repo, payment = test_setup
    order_id = uuid4()
    # Window expired 1 day ago
    payment.orders[order_id] = OrderInfo(
        order_id=order_id,
        auction_id=uuid4(),
        buyer_id=BUYER,
        seller_id=SELLER,
        state="SHIPPED",
        protection_window_ends_at=NOW - timedelta(days=1),
    )

    res = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "NOT_AS_DESCRIBED", "description": "Color is wrong"},
        headers=bearer(BUYER),
    )
    assert res.status_code == 409
    assert res.json()["code"] == "WINDOW_CLOSED"
    assert order_id not in payment.frozen


def test_non_buyer_cannot_raise_dispute(test_setup):
    client, repo, payment = test_setup
    order_id = uuid4()
    payment.orders[order_id] = OrderInfo(
        order_id=order_id,
        auction_id=uuid4(),
        buyer_id=BUYER,
        seller_id=SELLER,
        state="SHIPPED",
        protection_window_ends_at=NOW + timedelta(days=2),
    )

    res = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "DAMAGED_IN_TRANSIT", "description": "Broken screen"},
        headers=bearer(OTHER_USER),
    )
    assert res.status_code == 403


def test_duplicate_open_dispute_conflict(test_setup):
    client, repo, payment = test_setup
    order_id = uuid4()
    payment.orders[order_id] = OrderInfo(
        order_id=order_id,
        auction_id=uuid4(),
        buyer_id=BUYER,
        seller_id=SELLER,
        state="SHIPPED",
        protection_window_ends_at=NOW + timedelta(days=3),
    )

    # First dispute
    res1 = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "COUNTERFEIT", "description": "Fake item"},
        headers=bearer(BUYER),
    )
    assert res1.status_code == 201

    # Second dispute
    res2 = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "OTHER", "description": "Second complaint"},
        headers=bearer(BUYER),
    )
    assert res2.status_code == 409


def test_add_evidence_photo_and_seller_response(test_setup):
    client, repo, payment = test_setup
    order_id = uuid4()
    payment.orders[order_id] = OrderInfo(
        order_id=order_id,
        auction_id=uuid4(),
        buyer_id=BUYER,
        seller_id=SELLER,
        state="SHIPPED",
        protection_window_ends_at=NOW + timedelta(days=3),
    )

    d_res = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "DAMAGED_IN_TRANSIT", "description": "Damaged box"},
        headers=bearer(BUYER),
    )
    dispute_id = d_res.json()["id"]

    # Buyer submits photo evidence
    e1 = client.post(
        f"/api/v1/disputes/{dispute_id}/evidence",
        json={"kind": "PHOTO", "object_key": "disputes/photos/box.jpg"},
        headers=bearer(BUYER),
    )
    assert e1.status_code == 201
    assert e1.json()["kind"] == "PHOTO"

    # Seller submits response
    e2 = client.post(
        f"/api/v1/disputes/{dispute_id}/evidence",
        json={"kind": "SELLER_RESPONSE", "body": "Box was packaged with bubble wrap."},
        headers=bearer(SELLER),
    )
    assert e2.status_code == 201
    assert e2.json()["kind"] == "SELLER_RESPONSE"

    # List evidence
    ev_list = client.get(f"/api/v1/disputes/{dispute_id}/evidence", headers=bearer(BUYER))
    assert ev_list.status_code == 200
    assert len(ev_list.json()) == 2
