"""Saga coordination and compensation (#63): the domain rules, the S2 compensation path, the
saga_steps log and its PostgreSQL statements."""

import asyncio
from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.adapters.kafka_producer import build_settlement_step
from app.adapters.repository import PostgresPaymentRepository
from app.domain import orders as machine
from app.domain.invoice import issue_invoice
from app.domain.ledger import EntryType, LedgerEntry, LedgerError, capture_entry, hold_entries
from app.domain.saga import (
    PartialSettlement,
    Step,
    StepStatus,
    check_no_partial_settlement,
    reversal_entries,
    step_record,
)
from app.payment_port.mock_adapter import MockPaymentAdapter
from tests.support import NOW, Harness, order
from tests.test_postgres_repo import FakePool, order_row


def stored(entries):
    return [replace(e, id=i, created_at=NOW) for i, e in enumerate(entries, start=1)]


def captured_order():
    return machine.capture_succeeded(machine.authorize(order(), "mock_pay_1", NOW),
                                     "mock_pay_1", NOW)


# ---------------------------------------------------------------------- domain


def test_step_records_carry_a_key_per_step_and_a_bounded_error():
    o = order()
    record = step_record(o, Step.S2, StepStatus.FAILED, "x" * 900)
    assert record.idempotency_key == f"order:{o.id}:saga-capture"
    assert len(record.last_error) == 500
    assert record.saga_id == o.saga_id and record.attempts == 1
    assert step_record(o, Step.S1, StepStatus.DONE).last_error is None
    keys = {step_record(o, step, StepStatus.DONE).idempotency_key for step in Step}
    assert len(keys) == 4


def test_reversal_entries_undo_custody_newest_first():
    held = machine.hold(captured_order(), NOW)
    rows = stored([capture_entry(held, "mock_pay_1"), *hold_entries(held)])
    reversal = reversal_entries(held, rows)
    assert [(r.amount, r.compensates_id) for r in reversal] == [
        (Decimal("99.00"), 3), (Decimal("-1349.00"), 1)]  # the zero HOLD marker needs none
    assert all(r.entry_type is EntryType.COMPENSATION for r in reversal)
    assert sum(r.amount for r in rows + reversal) == 0


def test_a_retried_reversal_adds_nothing_twice():
    o = captured_order()
    rows = stored([capture_entry(o, "mock_pay_1")])
    first = reversal_entries(o, rows)
    assert reversal_entries(o, stored([*rows, *first])) == []


def test_only_stored_rows_can_be_reversed():
    o = captured_order()
    with pytest.raises(LedgerError):
        reversal_entries(o, [capture_entry(o, "mock_pay_1")])


def test_the_no_partial_settlement_invariant():
    o = order()
    invoice = issue_invoice(o, invoice_id=uuid4())
    check_no_partial_settlement(o, invoice, [])
    capture = stored([capture_entry(o, "p")])
    bad = [
        (o, None, []),  # no invoice
        (o, invoice, capture),  # money before capture
        (o, replace(invoice, voided_at=NOW), []),  # voided but live
        (captured_order(), invoice, []),  # CAPTURED with no CAPTURE row
        (machine.hold(captured_order(), NOW), invoice, capture),  # IN_ESCROW missing HOLD
        (machine.cancel(o, NOW), invoice, []),  # cancelled, invoice live
        (replace(o, state="CANCELLED"), replace(invoice, voided_at=NOW), capture),  # money kept
    ]
    for args in bad:
        with pytest.raises(PartialSettlement):
            check_no_partial_settlement(*args)
    unreversed = stored([capture_entry(o, "p"),
                         LedgerEntry(o.id, EntryType.COMPENSATION, Decimal("-1349.00"), "INR",
                                     "k", compensates_id=99)])
    with pytest.raises(PartialSettlement, match="unreversed capture"):
        check_no_partial_settlement(replace(o, state="CANCELLED"),
                                    replace(invoice, voided_at=NOW), unreversed)


def test_o4a_cancels_only_a_captured_order():
    assert machine.cancel_after_capture(captured_order(), NOW).state == "CANCELLED"
    with pytest.raises(machine.IllegalOrderTransition):
        machine.cancel_after_capture(order(), NOW)


def test_a_compensated_event_names_the_reversal_it_made():
    o = machine.cancel_after_capture(captured_order(), NOW)
    event = build_settlement_step(event_id=uuid4(), order=o, step="COMPENSATED",
                                  occurred_at=NOW, operation="reverse-capture")
    assert event["idempotency_key"] == f"order:{o.id}:reverse-capture"
    plain = build_settlement_step(event_id=uuid4(), order=o, step="COMPENSATED", occurred_at=NOW)
    assert plain["idempotency_key"] == f"order:{o.id}:compensate-s1"


# ---------------------------------------------------------------------- service


def paid(harness: Harness) -> UUID:
    opened = harness.opened()
    response = harness.pay(opened["order_id"])
    assert response.status_code in (200, 500), response.text
    return UUID(opened["order_id"])


def steps(harness: Harness, order_id: UUID) -> dict[str, str]:
    o = harness.repo.orders[order_id]
    return {r.step.value: r.status.value
            for r in asyncio.run(harness.repo.saga_steps(o.saga_id))}


def test_a_settled_order_has_every_forward_step_done(harness):
    order_id = paid(harness)
    assert harness.repo.orders[order_id].state == "IN_ESCROW"
    assert steps(harness, order_id) == {"S1": "DONE", "S2": "DONE", "S3": "DONE", "S4": "DONE"}


def test_s2_is_compensated_when_s3_cannot_succeed(harness):
    order_id = UUID(harness.opened()["order_id"])
    harness.pay(str(order_id))
    o = harness.repo.orders[order_id]
    # Put the order back to CAPTURED as if S3 never ran, then make S3 impossible.
    harness.repo.orders[order_id] = replace(o, state="CAPTURED", version=o.version + 1)
    harness.repo.entries = [e for e in harness.repo.entries
                            if e.entry_type is EntryType.CAPTURE]
    cancelled = asyncio.run(harness.service.compensate_capture(
        harness.repo.orders[order_id], failure="S3: injected"))
    assert cancelled.state == "CANCELLED"
    ledger = harness.ledger(str(order_id))
    assert [row["entry_type"] for row in ledger] == ["CAPTURE", "COMPENSATION"]
    assert sum(Decimal(row["amount"]) for row in ledger) == 0
    assert harness.port.captured[o.capture_ref] == Decimal("0.00")  # refunded in full
    assert steps(harness, order_id) == {"S1": "COMPENSATED", "S2": "COMPENSATED",
                                        "S3": "FAILED", "S4": "DONE"}
    assert harness.events.types(order_id)[-1] == "COMPENSATED"
    assert harness.events.events[-1]["idempotency_key"].endswith(":reverse-capture")
    metrics = harness.client.get("/metrics").text
    assert 'payment_saga_compensations_total{step="S2"} 1.0' in metrics


def test_a_declined_capture_records_s2_failed_and_s1_compensated():
    port = MockPaymentAdapter()
    harness = Harness(port=port)
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    port._declines.add(f"order:{order_id}:capture")
    harness.pay(opened["order_id"])
    assert harness.repo.orders[order_id].state == "CANCELLED"
    assert steps(harness, order_id) == {"S1": "COMPENSATED", "S2": "FAILED"}


def test_an_unpaid_order_compensates_s1_only(harness):
    order_id = UUID(harness.opened()["order_id"])
    harness.clock.advance(hours=49)
    asyncio.run(harness.service.run_due_work())
    assert steps(harness, order_id) == {"S1": "COMPENSATED"}


# ---------------------------------------------------------------------- PostgreSQL


async def test_saga_steps_are_upserted_in_the_order_transaction():
    pool = FakePool()
    o = order()
    record = step_record(o, Step.S1, StepStatus.DONE)
    await PostgresPaymentRepository(pool).create_order(
        o, issue_invoice(o, invoice_id=uuid4()), steps=[record])
    upsert = pool.statements()[-1]
    assert upsert.startswith("INSERT INTO payment.saga_steps")
    assert "ON CONFLICT (saga_id, step)" in upsert
    assert "attempts = saga_steps.attempts + 1" in upsert
    assert pool.log[-2][1] == (o.saga_id, "S1", o.id, "DONE", record.idempotency_key, None,
                               o.created_at)
    assert pool.log[-1] == "COMMIT"

    pool = FakePool()
    cancelled = machine.cancel(o, NOW)
    await PostgresPaymentRepository(pool).save(
        o, cancelled, void_invoice_at=NOW,
        steps=[step_record(o, Step.S1, StepStatus.COMPENSATED, "unpaid")])
    assert pool.statements()[-1].startswith("INSERT INTO payment.saga_steps")
    assert pool.log[-2][1][3:7] == ("COMPENSATED", f"order:{o.id}:saga-invoice", "unpaid",
                                    cancelled.updated_at)


async def test_saga_steps_and_stuck_captures_are_read_back():
    o = order()
    row = {"saga_id": o.saga_id, "step": "S2", "order_id": o.id, "status": "FAILED",
           "idempotency_key": "k", "last_error": "transient", "attempts": 3}
    records = await PostgresPaymentRepository(FakePool(rows=[row])).saga_steps(o.saga_id)
    assert records[0].step is Step.S2 and records[0].status is StepStatus.FAILED
    assert records[0].attempts == 3
    pool = FakePool(rows=[order_row(o)])
    assert await PostgresPaymentRepository(pool).stuck_captures(NOW, 5) == [o]
    sql, args = pool.log[0]
    assert "state = 'CAPTURED' AND updated_at <= $1" in sql and args == (NOW, 5)
