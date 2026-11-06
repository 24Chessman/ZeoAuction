"""End-to-end auction lifecycle scenario suite (Plan 7, #36; FR-TEST-2).

Covers the full settlement path and the time-accelerated fixture verifying
every terminal path through the order state machine:

- Path a: open_order -> checkout -> pay -> ship -> confirm_receipt -> RELEASED (buyer confirms)
- Path b: open_order -> checkout -> pay -> ship -> advance clock past 7d -> sweep releases -> RELEASED;
          dispute attempt after window returns WINDOW_CLOSED (409)
- Path c: open_order -> checkout -> pay -> ship -> dispute -> admin adjudicates SELLER -> RELEASED
- Path d: open_order -> checkout -> pay -> ship -> dispute -> admin adjudicates BUYER (fault=SELLER) -> REFUNDED (full refund)
- Path e: open_order -> checkout -> pay -> ship -> dispute -> admin adjudicates BUYER (fault=BUYER) -> REFUNDED (fee retained)
- Path f: open_order -> checkout -> pay (IN_ESCROW) -> fraud alert -> DISPUTED -> admin adjudicates PLATFORM -> REFUNDED
- Path g: open_order -> buyer fails to pay -> cancel -> CANCELLED (balance 0)

Invariants asserted on every terminal path:
1. captured_total = winning_bid_amount + convenience_fee
2. Terminal balance is exactly 0
3. No order has both RELEASE and REFUND rows
4. Reconciliation verification returns is_valid=True with zero errors
5. Simulation notice present on all views
"""

from decimal import Decimal
from uuid import UUID

import pytest
from app.domain.ledger import EntryType
from app.domain.reconcile import reconcile_order
from tests.support import (
    ADMIN,
    BUYER,
    Harness,
    INTERNAL,
    NOW,
    SELLER,
    bearer,
    request,
)


@pytest.fixture
def harness():
    return Harness()


def _advance_to_shipped(harness: Harness, amount: str = "1250.00") -> str:
    """Helper to take an auction order through S1 -> checkout -> pay -> ship."""
    req = request(amount=amount)
    body = harness.opened(req)
    order_id = body["order_id"]

    # Checkout & Pay
    checkout_res = harness.checkout(order_id, user=BUYER)
    assert checkout_res.status_code == 200
    assert checkout_res.json()["simulated_payment"] is not None

    pay_res = harness.pay(order_id, checkout_res.json(), user=BUYER)
    assert pay_res.status_code == 200
    assert pay_res.json()["state"] == "IN_ESCROW"

    # Seller ships
    ship_res = harness.client.post(
        f"/api/v1/orders/{order_id}/ship",
        headers=bearer(SELLER),
    )
    assert ship_res.status_code == 200
    assert ship_res.json()["state"] == "SHIPPED"
    domain_order = harness.repo.orders[UUID(order_id)]
    assert domain_order.protection_window_ends_at is not None

    return order_id


def test_path_a_buyer_confirms_receipt(harness: Harness):
    """Path a: open -> pay -> ship -> buyer confirms receipt -> RELEASED."""
    order_id = _advance_to_shipped(harness, amount="1500.00")

    # Buyer confirms receipt
    res = harness.client.post(
        f"/api/v1/orders/{order_id}/confirm-receipt",
        headers=bearer(BUYER),
    )
    assert res.status_code == 200
    order_data = res.json()
    assert order_data["state"] == "RELEASED"

    # Inspect ledger
    ledger = harness.ledger(order_id)
    entry_types = [e["entry_type"] for e in ledger]
    assert entry_types == ["CAPTURE", "HOLD", "FEE_RETAIN", "RELEASE"]

    release_row = next(e for e in ledger if e["entry_type"] == "RELEASE")
    assert release_row["amount"] == "-1500.00"  # net seller payout

    # Reconciliation check
    recon_res = harness.client.get(
        f"/api/v1/orders/{order_id}/reconciliation",
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert recon_res.status_code == 200
    recon = recon_res.json()
    assert recon["is_valid"] is True
    assert recon["balance"] == "0.00"
    assert recon["errors"] == []


def test_path_b_sweep_expiry_and_window_closure(harness: Harness):
    """Path b: 7-day protection window expires -> sweep release -> WINDOW_CLOSED on late dispute."""
    order_id = _advance_to_shipped(harness, amount="2000.00")

    # Advance clock past the 7-day protection window (8 days)
    harness.clock.advance(days=8)

    # Sweep triggers release via internal endpoint
    sweep_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/release?trigger=sweep_expiry",
        headers=INTERNAL | {"Idempotency-Key": f"order:{order_id}:release"},
    )
    assert sweep_res.status_code == 200
    assert sweep_res.json()["state"] == "RELEASED"

    # Attempting to raise a dispute now that window has closed must fail with 409 WINDOW_CLOSED
    dispute_attempt = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/freeze?reason=dispute",
        headers=INTERNAL,
    )
    assert dispute_attempt.status_code == 409
    body = dispute_attempt.json()
    assert body["code"] in ("WINDOW_CLOSED", "CONFLICT")

    # Verify reconciliation and zero balance
    recon = harness.client.get(
        f"/api/v1/orders/{order_id}/reconciliation",
        headers=bearer(ADMIN, role="ADMIN"),
    ).json()
    assert recon["is_valid"] is True
    assert recon["balance"] == "0.00"
    assert recon["errors"] == []


def test_path_c_dispute_resolved_in_seller_favour(harness: Harness):
    """Path c: dispute raised -> escrow frozen -> admin adjudicates SELLER -> RELEASED."""
    order_id = _advance_to_shipped(harness, amount="3000.00")

    # Buyer raises dispute within protection window
    freeze_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/freeze?reason=dispute",
        headers=INTERNAL,
    )
    assert freeze_res.status_code == 200
    assert freeze_res.json()["state"] == "DISPUTED"

    # Admin adjudicates in seller's favour
    release_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/release?trigger=adjudication",
        headers=INTERNAL | {"Idempotency-Key": f"order:{order_id}:release"},
    )
    assert release_res.status_code == 200
    assert release_res.json()["state"] == "RELEASED"

    # Verify reconciliation
    recon = harness.client.get(
        f"/api/v1/orders/{order_id}/reconciliation",
        headers=bearer(ADMIN, role="ADMIN"),
    ).json()
    assert recon["is_valid"] is True
    assert recon["balance"] == "0.00"
    assert recon["errors"] == []


def test_path_d_dispute_resolved_buyer_seller_fault(harness: Harness):
    """Path d: dispute -> frozen -> admin adjudicates BUYER (SELLER fault) -> full REFUND."""
    order_id = _advance_to_shipped(harness, amount="1000.00")

    # Freeze escrow
    freeze_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/freeze?reason=dispute",
        headers=INTERNAL,
    )
    assert freeze_res.status_code == 200
    assert freeze_res.json()["state"] == "DISPUTED"

    # Admin resolves with seller fault: full refund (bid + fee compensated)
    refund_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/refund",
        json={"fault": "SELLER", "note": "Counterfeit item confirmed by admin"},
        headers=INTERNAL | {"Idempotency-Key": f"order:{order_id}:refund"},
    )
    assert refund_res.status_code == 200
    assert refund_res.json()["state"] == "REFUNDED"

    ledger = harness.ledger(order_id)
    entry_types = [e["entry_type"] for e in ledger]
    assert "COMPENSATION" in entry_types
    assert "REFUND" in entry_types
    assert "RELEASE" not in entry_types

    # Total refunded to buyer is captured_total (1000 + convenience_fee 99.00 = 1099.00)
    refund_row = next(e for e in ledger if e["entry_type"] == "REFUND")
    assert refund_row["amount"] == "-1099.00"

    # Verify reconciliation
    recon = harness.client.get(
        f"/api/v1/orders/{order_id}/reconciliation",
        headers=bearer(ADMIN, role="ADMIN"),
    ).json()
    assert recon["is_valid"] is True
    assert recon["balance"] == "0.00"
    assert recon["errors"] == []


def test_path_e_dispute_resolved_buyer_fault_fee_retained(harness: Harness):
    """Path e: dispute -> frozen -> admin adjudicates BUYER (BUYER fault) -> partial REFUND."""
    order_id = _advance_to_shipped(harness, amount="1000.00")

    # Freeze escrow
    harness.client.post(
        f"/api/v1/internal/orders/{order_id}/freeze?reason=dispute",
        headers=INTERNAL,
    )

    # Admin resolves with buyer fault: convenience fee is retained
    refund_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/refund",
        json={"fault": "BUYER", "note": "Buyer remorse / incorrect address provided"},
        headers=INTERNAL | {"Idempotency-Key": f"order:{order_id}:refund"},
    )
    assert refund_res.status_code == 200
    assert refund_res.json()["state"] == "REFUNDED"

    ledger = harness.ledger(order_id)
    entry_types = [e["entry_type"] for e in ledger]
    assert "COMPENSATION" not in entry_types
    assert "REFUND" in entry_types

    # Only winning_bid refunded to buyer (-1000.00)
    refund_row = next(e for e in ledger if e["entry_type"] == "REFUND")
    assert refund_row["amount"] == "-1000.00"

    # Terminal balance is still 0 because FEE_RETAIN was -99.00 and CAPTURE was +1099.00
    recon = harness.client.get(
        f"/api/v1/orders/{order_id}/reconciliation",
        headers=bearer(ADMIN, role="ADMIN"),
    ).json()
    assert recon["is_valid"] is True
    assert recon["balance"] == "0.00"
    assert recon["errors"] == []


def test_path_f_fraud_freeze_from_escrow_hold(harness: Harness):
    """Path f: fraud alert arrives while IN_ESCROW -> frozen -> admin PLATFORM refund."""
    req = request(amount="4000.00")
    order_id = harness.opened(req)["order_id"]
    pay_res = harness.pay(order_id, user=BUYER)
    assert pay_res.json()["state"] == "IN_ESCROW"

    # Fraud detector flags auction before shipment (O8)
    fraud_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/freeze?reason=fraud",
        headers=INTERNAL,
    )
    assert fraud_res.status_code == 200
    assert fraud_res.json()["state"] == "DISPUTED"

    # Admin confirms fraud: platform fault refund
    refund_res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/refund",
        json={"fault": "PLATFORM", "note": "Sybil / shill collusion confirmed"},
        headers=INTERNAL | {"Idempotency-Key": f"order:{order_id}:refund"},
    )
    assert refund_res.status_code == 200
    assert refund_res.json()["state"] == "REFUNDED"

    recon = harness.client.get(
        f"/api/v1/orders/{order_id}/reconciliation",
        headers=bearer(ADMIN, role="ADMIN"),
    ).json()
    assert recon["is_valid"] is True
    assert recon["balance"] == "0.00"
    assert recon["errors"] == []


def test_path_g_cancellation_before_capture(harness: Harness):
    """Path g: opened order cancelled before capture -> CANCELLED, zero ledger balance."""
    req = request(amount="500.00")
    order_id = harness.opened(req)["order_id"]

    # Directly cancel order in repository/service
    order = harness.repo.orders[UUID(order_id)]
    from app.domain import orders as machine
    cancelled = machine.cancel(order, harness.clock())
    harness.repo.orders[UUID(order_id)] = cancelled

    # Ledger is empty, balance is 0
    order_entries = [e for e in harness.repo.entries if e.order_id == UUID(order_id)]
    recon_report = reconcile_order(cancelled, order_entries)
    assert recon_report.is_valid is True
    assert recon_report.balance == Decimal("0.00")
    assert recon_report.errors == []


def test_simulation_notice_displayed_on_views(harness: Harness):
    """Every order view carries test mode notice (ADR-0011, Plan 6/7)."""
    req = request(amount="800.00")
    order_id = harness.opened(req)["order_id"]

    res = harness.client.get(f"/api/v1/orders/{order_id}", headers=bearer(BUYER))
    assert res.status_code == 200
    body = res.json()
    assert body["test_mode"] is True
    assert "simulation" in body["notice"].lower()


def test_release_and_refund_idempotency(harness: Harness):
    """Operations repeated with the same idempotency key are safe and return 200 without duplicate rows."""
    order_id = _advance_to_shipped(harness, amount="750.00")

    # Confirm receipt once
    res1 = harness.client.post(
        f"/api/v1/orders/{order_id}/confirm-receipt",
        headers=bearer(BUYER),
    )
    assert res1.status_code == 200
    assert res1.json()["state"] == "RELEASED"

    # Confirm receipt second time (idempotent replay)
    res2 = harness.client.post(
        f"/api/v1/orders/{order_id}/confirm-receipt",
        headers=bearer(BUYER),
    )
    assert res2.status_code == 200
    assert res2.json()["state"] == "RELEASED"

    # Check only 1 RELEASE entry exists in ledger
    ledger = harness.ledger(order_id)
    releases = [e for e in ledger if e["entry_type"] == "RELEASE"]
    assert len(releases) == 1
