"""Tests for refund execution and fee treatment by fault (Plan 6, #66; SDD Table 6.3).

Fault determines fee treatment:
- BUYER: fee retained, REFUND -winning_bid
- SELLER: fee refunded, COMPENSATION +fee, REFUND -captured_total
- PLATFORM: fee refunded, COMPENSATION +fee, REFUND -captured_total
"""

from decimal import Decimal
from dataclasses import replace
import pytest

from app.domain.ledger import EntryType, balance
from app.domain.refund import Fault, build_refund_entries, execute_refund
from app.main import build_app
from fastapi.testclient import TestClient

from tests.support import (
    ADMIN,
    BUYER,
    Clock,
    INTERNAL,
    NOW,
    SELLER,
    SETTINGS,
    bearer,
    order as make_order,
)
from tests.test_release import _setup_held_order


def test_unit_refund_buyer_fault():
    # winning_bid = 1000, fee = 25, captured = 1025
    order = replace(make_order("1000.00"), state="DISPUTED")
    entries = build_refund_entries(order, Fault.BUYER)
    assert len(entries) == 1
    assert entries[0].entry_type == EntryType.REFUND
    assert entries[0].amount == -Decimal("1000.00")
    assert entries[0].idempotency_key == order.idempotency_key("refund")


def test_unit_refund_seller_fault():
    # winning_bid = 1000, fee = 99 (ACTIVE_FEE), captured = 1099
    order = replace(make_order("1000.00"), state="DISPUTED")
    entries = build_refund_entries(order, Fault.SELLER)
    assert len(entries) == 2
    comp, refund = entries
    assert comp.entry_type == EntryType.COMPENSATION
    assert comp.amount == order.convenience_fee
    assert comp.idempotency_key == order.idempotency_key("compensate-fee")
    assert refund.entry_type == EntryType.REFUND
    assert refund.amount == -order.captured_total
    assert refund.idempotency_key == order.idempotency_key("refund")


def test_unit_refund_platform_fault():
    order = replace(make_order("1000.00"), state="DISPUTED")
    entries = build_refund_entries(order, Fault.PLATFORM)
    assert len(entries) == 2
    comp, refund = entries
    assert comp.entry_type == EntryType.COMPENSATION
    assert comp.amount == order.convenience_fee
    assert refund.entry_type == EntryType.REFUND
    assert refund.amount == -order.captured_total


def test_api_refund_buyer_fault(harness):
    order_id = _setup_held_order(harness, "1000.00")

    # Ship and freeze into DISPUTED
    harness.client.post(f"/api/v1/orders/{order_id}/ship", headers=bearer(SELLER))
    harness.client.post(f"/api/v1/internal/orders/{order_id}/freeze", headers=INTERNAL)

    # Adjudicate with BUYER fault
    res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/refund",
        json={"fault": "BUYER", "note": "buyer remorse"},
        headers=INTERNAL | {"Idempotency-Key": f"refund-{order_id}"},
    )
    assert res.status_code == 200
    assert res.json()["state"] == "REFUNDED"

    # Ledger check
    entries = harness.ledger(order_id)
    types = [e["entry_type"] for e in entries]
    assert "REFUND" in types
    assert "COMPENSATION" not in types
    refund_row = next(e for e in entries if e["entry_type"] == "REFUND")
    assert refund_row["amount"] == "-1000.00"


def test_api_refund_seller_fault(harness):
    order_id = _setup_held_order(harness, "1000.00")

    # Ship and freeze
    harness.client.post(f"/api/v1/orders/{order_id}/ship", headers=bearer(SELLER))
    harness.client.post(f"/api/v1/internal/orders/{order_id}/freeze", headers=INTERNAL)

    # Adjudicate with SELLER fault (full refund incl. fee)
    res = harness.client.post(
        f"/api/v1/internal/orders/{order_id}/refund",
        json={"fault": "SELLER", "note": "counterfeit goods confirmed"},
        headers=INTERNAL | {"Idempotency-Key": f"refund-{order_id}"},
    )
    assert res.status_code == 200
    assert res.json()["state"] == "REFUNDED"

    # Ledger check: both COMPENSATION and REFUND
    entries = harness.ledger(order_id)
    types = [e["entry_type"] for e in entries]
    assert "COMPENSATION" in types
    assert "REFUND" in types
    refund_row = next(e for e in entries if e["entry_type"] == "REFUND")
    assert refund_row["amount"] == "-1099.00"
    comp_row = next(e for e in entries if e["entry_type"] == "COMPENSATION")
    assert comp_row["amount"] == "99.00"
