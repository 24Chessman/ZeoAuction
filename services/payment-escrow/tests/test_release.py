"""Tests for escrow release execution across all three triggers (#65, Plan 6).

Triggers:
1. Buyer confirms receipt (trigger a)
2. Protection window expires with no dispute (sweep trigger b)
3. Admin adjudicates in seller's favour (adjudication trigger c)

All three converge on the same RELEASE ledger write:
    net = captured_total - convenience_fee (= winning_bid_amount)
with idempotency key:
    order:{id}:release
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.ledger import EntryType
from app.domain.orders import IllegalOrderTransition
from app.domain.release import ReleaseTrigger, execute_release
from app.main import build_app
from fastapi.testclient import TestClient

from tests.support import (
    ADMIN,
    BUYER,
    Clock,
    Harness,
    INTERNAL,
    NOW,
    SELLER,
    SETTINGS,
    bearer,
    order as make_order,
    request,
)


def _setup_held_order(harness, amount="1000.00"):
    """Helper to take an order through S1, Checkout, Confirm to IN_ESCROW."""
    req = request(amount)
    body = harness.opened(req)
    order_id = body["order_id"]
    pay_res = harness.pay(order_id)
    assert pay_res.status_code == 200
    assert pay_res.json()["state"] == "IN_ESCROW"
    return order_id


def test_unit_execute_release_all_three_triggers():
    order = make_order(amount="1000.00")
    order = order._replace(state="SHIPPED") if hasattr(order, "_replace") else order
    from dataclasses import replace
    shipped = replace(order, state="SHIPPED")

    # Trigger a: buyer confirm
    o_a, entry_a = execute_release(shipped, ReleaseTrigger.BUYER_CONFIRM, NOW)
    assert o_a.state == "RELEASED"
    assert entry_a.entry_type == EntryType.RELEASE
    assert entry_a.amount == -Decimal("1000.00")
    assert entry_a.idempotency_key == shipped.idempotency_key("release")

    # Trigger b: sweep expiry
    o_b, entry_b = execute_release(shipped, ReleaseTrigger.SWEEP_EXPIRY, NOW)
    assert o_b.state == "RELEASED"
    assert entry_b.entry_type == EntryType.RELEASE
    assert entry_b.amount == -Decimal("1000.00")
    assert entry_b.idempotency_key == shipped.idempotency_key("release")

    # Trigger c: adjudication in seller favour
    disputed = replace(order, state="DISPUTED")
    o_c, entry_c = execute_release(disputed, ReleaseTrigger.ADJUDICATE_SELLER, NOW)
    assert o_c.state == "RELEASED"
    assert entry_c.entry_type == EntryType.RELEASE
    assert entry_c.amount == -Decimal("1000.00")
    assert entry_c.idempotency_key == disputed.idempotency_key("release")


def test_guard_r1_refuses_release_when_open_dispute():
    from dataclasses import replace
    order = replace(make_order("1000.00"), state="SHIPPED")
    with pytest.raises(IllegalOrderTransition):
        execute_release(order, ReleaseTrigger.BUYER_CONFIRM, NOW, has_open_dispute=True)


def test_api_buyer_confirms_receipt(harness):
    order_id = _setup_held_order(harness, "1500.00")

    # Seller ships
    ship_res = harness.client.post(f"/api/v1/orders/{order_id}/ship", headers=bearer(SELLER))
    assert ship_res.status_code == 200
    assert ship_res.json()["state"] == "SHIPPED"

    # Buyer confirms receipt
    confirm_res = harness.client.post(f"/api/v1/orders/{order_id}/confirm-receipt", headers=bearer(BUYER))
    assert confirm_res.status_code == 200
    assert confirm_res.json()["state"] == "RELEASED"

    # Ledger check: RELEASE entry present
    entries = harness.ledger(order_id)
    types = [e["entry_type"] for e in entries]
    assert "RELEASE" in types
    release_entry = next(e for e in entries if e["entry_type"] == "RELEASE")
    assert release_entry["amount"] == "-1500.00"
    assert release_entry["idempotency_key"] == f"order:{order_id}:release"

    # Retried confirm is idempotent
    retry_res = harness.client.post(f"/api/v1/orders/{order_id}/confirm-receipt", headers=bearer(BUYER))
    assert retry_res.status_code == 200
    assert retry_res.json()["state"] == "RELEASED"


def test_api_sweep_expiry_release(harness):
    order_id = _setup_held_order(harness, "2000.00")

    # Seller ships
    harness.client.post(f"/api/v1/orders/{order_id}/ship", headers=bearer(SELLER))

    # Internal release by sweep
    rel_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/release?trigger=sweep_expiry",
        headers=INTERNAL | {"Idempotency-Key": f"order:{order_id}:release"},
    )
    assert rel_res.status_code == 200
    assert rel_res.json()["state"] == "RELEASED"

    # Ledger check
    release_entry = next(e for e in harness.ledger(order_id) if e["entry_type"] == "RELEASE")
    assert release_entry["amount"] == "-2000.00"


def test_api_adjudication_seller_release(harness):
    order_id = _setup_held_order(harness, "800.00")
    harness.client.post(f"/api/v1/orders/{order_id}/ship", headers=bearer(SELLER))

    # Freeze into DISPUTED
    harness.client.post(f"/api/v1/internal/orders/{order_id}/freeze", headers=INTERNAL)
    get_res = harness.client.get(f"/api/v1/orders/{order_id}", headers=bearer(BUYER))
    assert get_res.json()["state"] == "DISPUTED"

    # Internal release by adjudication
    rel_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/release?trigger=adjudicate_seller",
        headers=INTERNAL | {"Idempotency-Key": f"order:{order_id}:release"},
    )
    assert rel_res.status_code == 200
    assert rel_res.json()["state"] == "RELEASED"
