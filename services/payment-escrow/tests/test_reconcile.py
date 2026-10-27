"""Tests for per-order escrow ledger reconciliation (Plan 6, #66; SDD 4.3.2).

Invariants asserted:
1. captured_total = winning_bid_amount + convenience_fee
2. Terminal order rows sum to exactly zero (checked in FR-TEST-6)
3. No order ever gets both RELEASE and REFUND
4. In-escrow / shipped balance equals seller payout
"""

from dataclasses import replace
from decimal import Decimal
import pytest

from app.domain.ledger import (
    EntryType,
    LedgerEntry,
    capture_entry,
    hold_entries,
)
from app.domain.reconcile import reconcile_order
from app.domain.refund import build_refund_entries, Fault
from app.domain.release import build_release_entry

from tests.support import (
    NOW,
    order as make_order,
)


def test_reconcile_in_escrow_valid():
    order = make_order("1000.00") # fee = 25.00, captured = 1025.00
    order = replace(order, state="IN_ESCROW")
    entries = [
        capture_entry(order, "pay_123"),
        *hold_entries(order),
    ]
    report = reconcile_order(order, entries)
    assert report.is_valid is True
    assert report.balance == Decimal("1000.00")
    assert report.errors == []


def test_reconcile_released_order_valid():
    order = make_order("1000.00")
    order = replace(order, state="RELEASED")
    entries = [
        capture_entry(order, "pay_123"),
        *hold_entries(order),
        build_release_entry(order),
    ]
    report = reconcile_order(order, entries)
    assert report.is_valid is True
    assert report.balance == Decimal("0.00")
    assert report.errors == []


def test_reconcile_refunded_order_buyer_fault_valid():
    order = make_order("1000.00")
    order = replace(order, state="REFUNDED")
    refund_entries = build_refund_entries(order, Fault.BUYER)
    entries = [
        capture_entry(order, "pay_123"),
        *hold_entries(order),
        *refund_entries,
    ]
    report = reconcile_order(order, entries)
    assert report.is_valid is True
    assert report.balance == Decimal("0.00")
    assert report.errors == []


def test_reconcile_refunded_order_seller_fault_valid():
    order = make_order("1000.00")
    order = replace(order, state="REFUNDED")
    held_entries = [capture_entry(order, "pay_123"), *hold_entries(order)]
    refund_entries = build_refund_entries(order, Fault.SELLER, held_entries)
    entries = [*held_entries, *refund_entries]

    report = reconcile_order(order, entries)
    assert report.is_valid is True
    assert report.balance == Decimal("0.00")
    assert report.errors == []


def test_reconcile_detects_multiple_terminal_entries():
    order = make_order("1000.00")
    order = replace(order, state="RELEASED")
    entries = [
        capture_entry(order, "pay_123"),
        *hold_entries(order),
        build_release_entry(order),
        LedgerEntry(
            order_id=order.id,
            entry_type=EntryType.REFUND,
            amount=-Decimal("1000.00"),
            currency=order.currency,
            idempotency_key=order.idempotency_key("refund"),
        ),
    ]
    report = reconcile_order(order, entries)
    assert report.is_valid is False
    assert any("Multiple terminal entries" in e for e in report.errors)
    assert any("both RELEASE and REFUND" in e for e in report.errors)
