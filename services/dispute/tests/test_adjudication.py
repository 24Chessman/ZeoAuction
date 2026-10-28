"""Tests for admin adjudication API (#84, Plan 6)."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.dispute_repo import InMemoryDisputeRepository
from app.adapters.payment_client import InMemoryPaymentClient, OrderInfo
from app.main import build_app
from tests.support import (
    ADMIN,
    BUYER,
    JWT,
    NOW,
    SELLER,
    SETTINGS,
    bearer,
)
from zeo_common.audit import InMemoryAuditWriter


@pytest.fixture
def test_setup():
    repo = InMemoryDisputeRepository()
    payment = InMemoryPaymentClient()
    audit = InMemoryAuditWriter()
    app = build_app(
        SETTINGS,
        repo,
        payment_client=payment,
        audit_writer=audit,
        jwt_settings=JWT,
        clock=lambda: NOW,
    )
    client = TestClient(app)
    return client, repo, payment, audit


def _create_dispute(client, payment, order_id=None):
    order_id = order_id or uuid4()
    payment.orders[order_id] = OrderInfo(
        order_id=order_id,
        auction_id=uuid4(),
        buyer_id=BUYER,
        seller_id=SELLER,
        state="SHIPPED",
        protection_window_ends_at=NOW + timedelta(days=4),
    )
    res = client.post(
        f"/api/v1/orders/{order_id}/disputes",
        json={"reason_code": "NOT_AS_DESCRIBED", "description": "Item description discrepancy"},
        headers=bearer(BUYER),
    )
    assert res.status_code == 201
    return UUID(res.json()["id"]), order_id


def test_admin_start_review(test_setup):
    client, repo, payment, audit = test_setup
    dispute_id, order_id = _create_dispute(client, payment)

    res = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/review",
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert res.status_code == 200
    assert res.json()["state"] == "UNDER_REVIEW"

    # Audited
    audit_entries = audit.for_target("dispute", dispute_id)
    assert any(e.action == "DISPUTE_REVIEW" for e in audit_entries)


def test_admin_resolve_seller_favour(test_setup):
    client, repo, payment, audit = test_setup
    dispute_id, order_id = _create_dispute(client, payment)

    res = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/resolve",
        json={
            "outcome": "RESOLVED_SELLER",
            "note": "Seller provided proof of delivery and authenticity certificate.",
        },
        headers=bearer(ADMIN, role="ADMIN") | {"Idempotency-Key": f"res-{dispute_id}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "RESOLVED_SELLER"
    assert data["resolved_by"] == str(ADMIN)

    # Release command sent to Payment
    assert order_id in payment.released

    # Audited
    audit_entries = audit.for_target("dispute", dispute_id)
    assert any(e.action == "DISPUTE_RESOLVE" for e in audit_entries)

    # Idempotent retry
    retry = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/resolve",
        json={
            "outcome": "RESOLVED_SELLER",
            "note": "Seller provided proof of delivery.",
        },
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert retry.status_code == 200
    assert retry.json()["state"] == "RESOLVED_SELLER"


def test_admin_resolve_buyer_favour_requires_fault(test_setup):
    client, repo, payment, audit = test_setup
    dispute_id, order_id = _create_dispute(client, payment)

    # Resolving for buyer with no fault -> 422
    res = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/resolve",
        json={"outcome": "RESOLVED_BUYER", "note": "Buyer was right"},
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert res.status_code == 422


def test_admin_resolve_buyer_favour_with_fault(test_setup):
    client, repo, payment, audit = test_setup
    dispute_id, order_id = _create_dispute(client, payment)

    res = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/resolve",
        json={
            "outcome": "RESOLVED_BUYER",
            "fault": "SELLER",
            "note": "Item was counterfeit; full refund to buyer.",
        },
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "RESOLVED_BUYER"
    assert data["fault"] == "SELLER"

    # Refund command sent to Payment
    assert order_id in payment.refunded
    assert payment.refunded[order_id] == "SELLER"

    # Audit log check
    audit_entries = audit.for_target("dispute", dispute_id)
    assert any(e.action == "DISPUTE_RESOLVE" for e in audit_entries)
