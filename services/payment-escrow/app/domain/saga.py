"""Settlement saga: forward steps, their compensations, and the no-partial-settlement
invariant (#63; SDD 5.2.2 Table 5.2, 6.5; FR-PAY-6, NFR-REL-3).

Pure logic, no I/O. :class:`app.service.PaymentService` coordinates the steps; this module says
what each step's compensation writes and checks what must hold after any failure.

    Step  Forward (state after)                    Compensation
    S1    order + invoice           (INVOICED)     void the invoice, cancel the order (O4)
    S2    provider capture, CAPTURE (CAPTURED)     full reversal at the provider, COMPENSATION
                                                   rows equal and opposite, cancel (O4a)
    S3    HOLD + FEE_RETAIN rows    } one          nothing: S3 and S4 commit in one
    S4    state IN_ESCROW           } transaction  transaction, so neither exists without the other

A transient failure is retried with the step's **same** idempotency key, so settlement is
deferred, never abandoned or repeated: a parked capture (O3), or an order left CAPTURED by a
crash between S2 and S3. Only a definitive failure compensates. The ledger is append-only: a
compensation adds rows and never deletes one.

Progress is recorded per step in ``payment.saga_steps`` (one row per saga and step, upserted in
the same transaction as the order change it describes).
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.invoice import Invoice
from app.domain.ledger import ZERO, EntryType, LedgerEntry, LedgerError, balance, check_settled
from app.domain.orders import Order


class Step(StrEnum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"


# The order operation behind each step's idempotency key, order:{id}:saga-{operation}. The
# saga_steps keys are unique across the table, so they are kept apart from the ledger's keys.
OPERATION = {Step.S1: "invoice", Step.S2: "capture", Step.S3: "hold", Step.S4: "escrow"}
REVERSE_CAPTURE = "reverse-capture"  # the provider refund that compensates S2

# Order states in which no money has entered custody yet, and the ledger must be empty.
BEFORE_CAPTURE = frozenset({"INVOICED", "AUTHORIZED", "AWAITING_CAPTURE_RETRY"})


class PartialSettlement(AssertionError):
    """An order is in a state its ledger, invoice or steps contradict (NFR-REL-3)."""


@dataclass(frozen=True)
class SagaStepRecord:
    saga_id: UUID
    step: Step
    order_id: UUID
    status: StepStatus
    idempotency_key: str
    last_error: str | None = None
    attempts: int = 1


def step_record(order: Order, step: Step, status: StepStatus,
                error: str | None = None) -> SagaStepRecord:
    return SagaStepRecord(saga_id=order.saga_id, step=step, order_id=order.id, status=status,
                          idempotency_key=order.idempotency_key(f"saga-{OPERATION[step]}"),
                          last_error=error[:500] if error else None)


def reversal_entries(order: Order, entries: list[LedgerEntry]) -> list[LedgerEntry]:
    """COMPENSATION rows that bring the order's custody back to zero: one equal and opposite
    row per money row not already compensated, newest first. Rows already reversed are
    skipped, so a retried compensation adds nothing twice."""
    compensated = {e.compensates_id for e in entries if e.entry_type is EntryType.COMPENSATION}
    rows = []
    for entry in reversed(entries):
        if entry.entry_type is EntryType.COMPENSATION or entry.amount == ZERO:
            continue
        if entry.id is None:
            raise LedgerError("only stored ledger rows can be compensated")
        if entry.id in compensated:
            continue
        rows.append(LedgerEntry(
            order_id=order.id, entry_type=EntryType.COMPENSATION, amount=-entry.amount,
            currency=order.currency,
            idempotency_key=order.idempotency_key(f"compensate-{entry.id}"),
            saga_id=order.saga_id, compensates_id=entry.id,
            note=f"saga: reverses {entry.entry_type} #{entry.id}"))
    return rows


def check_no_partial_settlement(order: Order, invoice: Invoice | None,
                                entries: list[LedgerEntry]) -> None:
    """What every failure, at any step, must leave behind (NFR-REL-3):

    * before capture: no ledger rows, and a live invoice;
    * CAPTURED: exactly the CAPTURE row (S3 is still to come, or being retried);
    * IN_ESCROW: CAPTURE, HOLD and FEE_RETAIN, with custody equal to the seller's payout;
    * CANCELLED: the invoice voided and custody back to zero; a capture, if there was one,
      reversed by a COMPENSATION row.
    """
    if invoice is None:
        raise PartialSettlement(f"order {order.id} has no invoice")
    types = [e.entry_type for e in entries]
    if order.state in BEFORE_CAPTURE:
        if entries:
            raise PartialSettlement(f"{order.state} order {order.id} has ledger rows {types}")
        if invoice.voided_at is not None:
            raise PartialSettlement(f"{order.state} order {order.id} has a voided invoice")
    elif order.state == "CAPTURED":
        if types != [EntryType.CAPTURE] or balance(entries) != order.captured_total:
            raise PartialSettlement(f"CAPTURED order {order.id} has ledger rows {types}")
    elif order.state == "IN_ESCROW":
        try:
            check_settled(order, entries)
        except LedgerError as exc:
            raise PartialSettlement(str(exc)) from exc
    elif order.state == "CANCELLED":
        if invoice.voided_at is None:
            raise PartialSettlement(f"cancelled order {order.id} kept a live invoice")
        if balance(entries) != ZERO:
            raise PartialSettlement(f"cancelled order {order.id} still holds {balance(entries)}")
        reversed_ids = {e.compensates_id for e in entries
                        if e.entry_type is EntryType.COMPENSATION}
        for entry in entries:
            if entry.entry_type is EntryType.CAPTURE and entry.id not in reversed_ids:
                raise PartialSettlement(f"cancelled order {order.id} has an unreversed capture")
