"""Escrow ledger (#62): sign convention, invariants, one terminal row, append-only writes."""

import random
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.adapters.repository import InMemoryPaymentRepository
from app.domain import orders as machine
from app.domain.fees import FeeConfig
from app.domain.invoice import issue_invoice
from app.domain.ledger import (
    EntryType,
    LedgerEntry,
    LedgerError,
    balance,
    capture_entry,
    check_append,
    check_settled,
    check_sign,
    hold_entries,
)
from tests.support import NOW, order


def captured_order(amount: str = "1250.00"):
    o = machine.authorize(order(amount), "pay_1", NOW)
    return machine.capture_succeeded(o, "pay_1", NOW)


def entry(o, entry_type, amount, key=None, **extra):
    return LedgerEntry(order_id=o.id, entry_type=entry_type, amount=Decimal(amount),
                       currency=o.currency, idempotency_key=key or f"{entry_type}-{uuid4()}",
                       **extra)


def settled_entries(o):
    return [capture_entry(o, "pay_1"), *hold_entries(o)]


def test_settlement_writes_capture_hold_and_fee_retain():
    o = captured_order()
    rows = settled_entries(o)
    assert [(r.entry_type, r.amount, r.idempotency_key) for r in rows] == [
        (EntryType.CAPTURE, Decimal("1349.00"), f"order:{o.id}:capture"),
        (EntryType.HOLD, Decimal("0.00"), f"order:{o.id}:hold"),
        (EntryType.FEE_RETAIN, Decimal("-99.00"), f"order:{o.id}:fee"),
    ]
    check_append(o, [], rows)
    check_settled(o, rows)
    assert balance(rows) == Decimal("1250.00")  # exactly the seller's future payout


def test_a_zero_fee_writes_no_fee_retain_row():
    o = machine.open_order(
        machine.SettlementRequest(uuid4(), uuid4(), uuid4(), uuid4(), Decimal("10.00"), "INR"),
        order_id=uuid4(), saga_id=uuid4(), fee=FeeConfig("free", Decimal("0.00"), "INR"),
        provider="mock", now=NOW, payment_window=timedelta(hours=1))
    assert [r.entry_type for r in hold_entries(o)] == [EntryType.HOLD]


@pytest.mark.parametrize("entry_type, amount", [
    (EntryType.CAPTURE, "0.00"), (EntryType.CAPTURE, "-1.00"), (EntryType.HOLD, "1.00"),
    (EntryType.FEE_RETAIN, "99.00"), (EntryType.RELEASE, "1.00"), (EntryType.REFUND, "0.00"),
    (EntryType.COMPENSATION, "5.00"),  # a compensation must name the row it reverses
    (EntryType.CAPTURE, "1.001"),
])
def test_sign_convention(entry_type, amount):
    with pytest.raises(LedgerError):
        check_sign(entry(order(), entry_type, amount))


def test_amounts_are_never_floats():
    with pytest.raises(LedgerError):
        check_sign(replace(entry(order(), EntryType.CAPTURE, "1.00"), amount=1.0))


def test_capture_and_fee_must_match_the_order():
    o = captured_order()
    with pytest.raises(LedgerError, match="captured_total"):
        check_append(o, [], [entry(o, EntryType.CAPTURE, "1.00")])
    with pytest.raises(LedgerError, match="convenience fee"):
        check_append(o, [], [entry(o, EntryType.CAPTURE, "1349.00"),
                             entry(o, EntryType.FEE_RETAIN, "-1.00")])


def test_entries_belong_to_the_order_and_its_currency():
    o = captured_order()
    with pytest.raises(LedgerError):
        check_append(o, [], [replace(capture_entry(o, "p"), currency="USD")])
    with pytest.raises(LedgerError):
        check_append(o, [], [replace(capture_entry(o, "p"), order_id=uuid4())])


def test_an_idempotency_key_is_written_once():
    o = captured_order()
    rows = settled_entries(o)
    with pytest.raises(LedgerError, match="already in the ledger"):
        check_append(o, rows, [capture_entry(o, "pay_1")])


def test_at_most_one_release_or_refund():
    o = captured_order()
    rows = settled_entries(o)
    release = entry(o, EntryType.RELEASE, "-1250.00")
    check_append(o, rows, [release])
    with pytest.raises(LedgerError, match="at most once"):
        check_append(o, [*rows, release], [entry(o, EntryType.REFUND, "-1.00")])


def test_custody_never_goes_negative():
    o = captured_order()
    with pytest.raises(LedgerError, match="negative"):
        check_append(o, settled_entries(o), [entry(o, EntryType.RELEASE, "-1349.00")])


def test_settled_invariant_detects_missing_rows():
    o = captured_order()
    rows = settled_entries(o)
    for missing in range(3):
        with pytest.raises(LedgerError):
            check_settled(o, rows[:missing] + rows[missing + 1:])


def test_released_order_sums_to_zero_across_many_amounts():
    """A small form of the FR-TEST-6 property: every settled-then-released order balances."""
    rng = random.Random(9)
    for _ in range(200):
        amount = f"{rng.randint(1, 10_000_000)}.{rng.randint(0, 99):02d}"
        o = captured_order(amount)
        rows = settled_entries(o)
        release = entry(o, EntryType.RELEASE, f"-{o.captured_total - o.convenience_fee:.2f}")
        check_append(o, rows, [release])
        assert balance([*rows, release]) == 0


async def test_the_repository_refuses_a_bad_append_and_keeps_the_order():
    repo = InMemoryPaymentRepository()
    o = machine.authorize(order(), "pay_1", NOW)
    await repo.create_order(o, issue_invoice(o, invoice_id=uuid4()))
    captured = machine.capture_succeeded(o, "pay_1", NOW)
    with pytest.raises(LedgerError):
        await repo.save(o, captured, entries=[entry(captured, EntryType.CAPTURE, "1.00")])
    assert (await repo.get(o.id)).state == "AUTHORIZED"
    assert await repo.ledger(o.id) == []
