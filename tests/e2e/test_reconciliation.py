"""1000-Settlement reconciliation test (Plan 7, #67; AC-08).

Owner: Jaydip (#67).
Verifies that 1,000 orders settled across all terminal paths strictly maintain:
1. captured_total = winning_bid_amount + convenience_fee
2. Terminal balance is exactly 0 for every completed order
3. No order ever receives both a RELEASE and a REFUND ledger entry
4. Payout to seller equals captured_total - convenience_fee (= winning_bid_amount)
5. Zero reconciliation failures across the entire batch (AC-08)
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import time
from uuid import uuid4

import pytest
from app.domain import orders as machine
from app.domain.fees import ACTIVE_FEE
from app.domain.ledger import (
    EntryType,
    LedgerEntry,
    ZERO,
    capture_entry,
    hold_entries,
)
from app.domain.orders import Order, SettlementRequest, open_order
from app.domain.reconcile import ReconciliationReport, reconcile_order
from app.domain.refund import Fault, build_refund_entries
from app.domain.release import ReleaseTrigger, execute_release

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


def _create_and_fund_order(order_id, winning_bid: Decimal) -> tuple[Order, list[LedgerEntry]]:
    """Helper creating an order and taking it through capture and escrow hold."""
    req = SettlementRequest(
        auction_id=uuid4(),
        buyer_id=uuid4(),
        seller_id=uuid4(),
        winning_bid_id=uuid4(),
        winning_bid_amount=winning_bid,
        currency="INR",
    )
    o = open_order(
        req,
        order_id=order_id,
        saga_id=uuid4(),
        fee=ACTIVE_FEE,
        provider="mock",
        now=NOW,
        payment_window=timedelta(hours=48),
    )
    # Authorized -> Captured -> Hold
    auth_o = machine.authorize(o, f"pay_{order_id.hex[:12]}", NOW)
    cap_o = machine.capture_succeeded(auth_o, f"cap_{order_id.hex[:12]}", NOW)
    held_o = machine.hold(cap_o, NOW)

    entries = [capture_entry(cap_o, NOW)]
    entries.extend(hold_entries(held_o))
    return held_o, entries


def test_1000_settlement_reconciliation():
    """Run 1,000 orders across various terminal states and verify zero reconciliation failures."""
    start_time = time.perf_counter()

    orders: list[Order] = []
    ledgers: dict[object, list[LedgerEntry]] = {}

    # Distribution of 1,000 orders:
    # 1. 400 RELEASED via buyer confirmation (trigger a)
    # 2. 250 RELEASED via sweep expiry (trigger b)
    # 3. 100 RELEASED via admin adjudication for seller (trigger c)
    # 4. 100 REFUNDED via seller fault (full refund + fee compensation)
    # 5. 50 REFUNDED via platform fault (full refund + fee compensation)
    # 6. 50 REFUNDED via buyer fault (convenience fee retained)
    # 7. 50 CANCELLED before capture (compensate S1, zero ledger)

    order_counter = 0

    # Group 1: 400 RELEASED via buyer confirmation
    for i in range(400):
        order_counter += 1
        oid = uuid4()
        bid_amount = Decimal(str(500 + (i % 500) * 10)) + Decimal("0.00")
        o, entries = _create_and_fund_order(oid, bid_amount)
        shipped = machine.mark_shipped(o, NOW)
        released, rel_entry = execute_release(shipped, ReleaseTrigger.BUYER_CONFIRM, NOW)
        entries.append(rel_entry)
        orders.append(released)
        ledgers[oid] = entries

    # Group 2: 250 RELEASED via sweep expiry
    for i in range(250):
        order_counter += 1
        oid = uuid4()
        bid_amount = Decimal(str(1000 + (i % 250) * 15)) + Decimal("0.00")
        o, entries = _create_and_fund_order(oid, bid_amount)
        shipped = machine.mark_shipped(o, NOW)
        future = NOW + timedelta(days=8)
        released, rel_entry = execute_release(shipped, ReleaseTrigger.SWEEP_EXPIRY, future)
        entries.append(rel_entry)
        orders.append(released)
        ledgers[oid] = entries

    # Group 3: 100 RELEASED via admin dispute adjudication for seller
    for i in range(100):
        order_counter += 1
        oid = uuid4()
        bid_amount = Decimal(str(2000 + (i % 100) * 20)) + Decimal("0.00")
        o, entries = _create_and_fund_order(oid, bid_amount)
        shipped = machine.mark_shipped(o, NOW)
        disputed = machine.raise_dispute(shipped, NOW + timedelta(days=2))
        released, rel_entry = execute_release(disputed, ReleaseTrigger.ADJUDICATE_SELLER, NOW + timedelta(days=4))
        entries.append(rel_entry)
        orders.append(released)
        ledgers[oid] = entries

    # Group 4: 100 REFUNDED via seller fault (full refund + fee compensation)
    for i in range(100):
        order_counter += 1
        oid = uuid4()
        bid_amount = Decimal(str(1500 + (i % 100) * 25)) + Decimal("0.00")
        o, entries = _create_and_fund_order(oid, bid_amount)
        shipped = machine.mark_shipped(o, NOW)
        disputed = machine.raise_dispute(shipped, NOW + timedelta(days=2))
        refunded = machine.adjudicate_buyer(disputed, NOW + timedelta(days=4))
        refund_entries = build_refund_entries(disputed, Fault.SELLER)
        entries.extend(refund_entries)
        orders.append(refunded)
        ledgers[oid] = entries

    # Group 5: 50 REFUNDED via platform fault (full refund + fee compensation)
    for i in range(50):
        order_counter += 1
        oid = uuid4()
        bid_amount = Decimal(str(3000 + (i % 50) * 50)) + Decimal("0.00")
        o, entries = _create_and_fund_order(oid, bid_amount)
        # Frozen from IN_ESCROW via fraud detector
        disputed = machine.fraud_dispute(o, NOW + timedelta(hours=6))
        refunded = machine.adjudicate_buyer(disputed, NOW + timedelta(hours=12))
        refund_entries = build_refund_entries(disputed, Fault.PLATFORM)
        entries.extend(refund_entries)
        orders.append(refunded)
        ledgers[oid] = entries

    # Group 6: 50 REFUNDED via buyer fault (convenience fee retained)
    for i in range(50):
        order_counter += 1
        oid = uuid4()
        bid_amount = Decimal(str(800 + (i % 50) * 10)) + Decimal("0.00")
        o, entries = _create_and_fund_order(oid, bid_amount)
        shipped = machine.mark_shipped(o, NOW)
        disputed = machine.raise_dispute(shipped, NOW + timedelta(days=1))
        refunded = machine.adjudicate_buyer(disputed, NOW + timedelta(days=3))
        refund_entries = build_refund_entries(disputed, Fault.BUYER)
        entries.extend(refund_entries)
        orders.append(refunded)
        ledgers[oid] = entries

    # Group 7: 50 CANCELLED before capture (unpaid or abandoned)
    for i in range(50):
        order_counter += 1
        oid = uuid4()
        bid_amount = Decimal(str(250 + (i % 50) * 5)) + Decimal("0.00")
        req = SettlementRequest(
            auction_id=uuid4(),
            buyer_id=uuid4(),
            seller_id=uuid4(),
            winning_bid_id=uuid4(),
            winning_bid_amount=bid_amount,
            currency="INR",
        )
        o = open_order(
            req,
            order_id=oid,
            saga_id=uuid4(),
            fee=ACTIVE_FEE,
            provider="mock",
            now=NOW,
            payment_window=timedelta(hours=48),
        )
        cancelled = machine.cancel(o, NOW + timedelta(hours=49))
        orders.append(cancelled)
        ledgers[oid] = []

    assert len(orders) == 1000
    assert order_counter == 1000

    # Run reconciliation on every single order
    reports: list[ReconciliationReport] = []
    failures: list[ReconciliationReport] = []

    for o in orders:
        report = reconcile_order(o, ledgers[o.id])
        reports.append(report)
        if not report.is_valid:
            failures.append(report)

    elapsed = time.perf_counter() - start_time

    # AC-08: Zero failures across 1,000 settlements
    assert len(failures) == 0, f"Found {len(failures)} reconciliation failures: {[f.errors for f in failures[:5]]}"
    assert all(r.is_valid for r in reports)
    assert all(r.balance == ZERO for r in reports)

    # Invariant assertions across the entire cohort
    terminal_counts = {}
    for o in orders:
        terminal_counts[o.state] = terminal_counts.get(o.state, 0) + 1

    assert terminal_counts == {"RELEASED": 750, "REFUNDED": 200, "CANCELLED": 50}

    # Ensure no order has both RELEASE and REFUND
    for oid, entries in ledgers.items():
        has_rel = any(e.entry_type == EntryType.RELEASE for e in entries)
        has_ref = any(e.entry_type == EntryType.REFUND for e in entries)
        assert not (has_rel and has_ref), f"Order {oid} has both RELEASE and REFUND"

    print(
        f"\n[RECONCILIATION AUDIT #67] Successfully reconciled {len(reports)} orders in {elapsed:.3f}s. "
        f"Zero failures (AC-08 passed). Invariants 100% held."
    )
