"""The append-only escrow ledger: entries, sign convention and invariants (#62, SDD 4.3.2).

Pure logic, no I/O. The ledger is the single source of monetary truth. Rows are signed
movements of platform custody for one order and are never updated or deleted; a mistake is
corrected with a COMPENSATION row (ADR-0004). The database enforces the same rules
(``infra/postgres/init/60-payment.sql``): the sign check, the append-only trigger, a unique
idempotency key per row and at most one RELEASE/REFUND per order. This module checks them
before anything is written, so a bug is caught in a unit test rather than by the database.

    CAPTURE       > 0   buyer funds captured into custody (= captured_total)
    HOLD          = 0   marker: the captured total is under escrow hold
    FEE_RETAIN    < 0   the flat fee moved out of custody to platform revenue
    RELEASE       < 0   net payout to the seller (captured_total - fee)
    REFUND        < 0   reversal to the buyer
    COMPENSATION <> 0   equal-and-opposite reversal of an earlier row
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.domain.orders import Order


class EntryType(StrEnum):
    CAPTURE = "CAPTURE"
    HOLD = "HOLD"
    FEE_RETAIN = "FEE_RETAIN"
    RELEASE = "RELEASE"
    REFUND = "REFUND"
    COMPENSATION = "COMPENSATION"


TERMINAL_ENTRIES = frozenset({EntryType.RELEASE, EntryType.REFUND})
ZERO = Decimal("0.00")


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class LedgerEntry:
    order_id: UUID
    entry_type: EntryType
    amount: Decimal
    currency: str
    idempotency_key: str
    saga_id: UUID | None = None
    provider_ref: str | None = None
    compensates_id: int | None = None
    note: str | None = None
    id: int | None = None
    created_at: datetime | None = None


def check_sign(entry: LedgerEntry) -> None:
    """The sign convention of ``ledger_sign_convention`` in the payment schema."""
    amount = entry.amount
    if not isinstance(amount, Decimal):
        raise LedgerError("ledger amounts are Decimal, never float")
    if amount != amount.quantize(Decimal("0.01")):
        raise LedgerError(f"{entry.entry_type} amount {amount} has more than two decimals")
    valid = {
        EntryType.CAPTURE: amount > 0,
        EntryType.HOLD: amount == 0,
        EntryType.FEE_RETAIN: amount < 0,
        EntryType.RELEASE: amount < 0,
        EntryType.REFUND: amount < 0,
        EntryType.COMPENSATION: amount != 0 and entry.compensates_id is not None,
    }[entry.entry_type]
    if not valid:
        raise LedgerError(f"{entry.entry_type} {amount} breaks the ledger sign convention")


def balance(entries: Iterable[LedgerEntry]) -> Decimal:
    """Money still in platform custody for the order (zero once it is terminal)."""
    return sum((entry.amount for entry in entries), ZERO)


def capture_entry(order: Order, capture_ref: str) -> LedgerEntry:
    """S2: the captured total enters custody."""
    return LedgerEntry(order_id=order.id, entry_type=EntryType.CAPTURE,
                       amount=order.captured_total, currency=order.currency,
                       idempotency_key=order.idempotency_key("capture"), saga_id=order.saga_id,
                       provider_ref=capture_ref)


def hold_entries(order: Order) -> list[LedgerEntry]:
    """S3: the hold marker and the fee moved to platform revenue. A zero fee writes no
    FEE_RETAIN row (the sign convention forbids a zero movement)."""
    entries = [LedgerEntry(order_id=order.id, entry_type=EntryType.HOLD, amount=ZERO,
                           currency=order.currency, idempotency_key=order.idempotency_key("hold"),
                           saga_id=order.saga_id)]
    if order.convenience_fee > 0:
        entries.append(LedgerEntry(
            order_id=order.id, entry_type=EntryType.FEE_RETAIN, amount=-order.convenience_fee,
            currency=order.currency, idempotency_key=order.idempotency_key("fee"),
            saga_id=order.saga_id, note=f"fee_version {order.fee_version}"))
    return entries


def check_append(order: Order, existing: list[LedgerEntry], new: list[LedgerEntry]) -> None:
    """Refuse rows that would break an invariant once appended to ``existing``."""
    keys = {entry.idempotency_key for entry in existing}
    terminal = any(entry.entry_type in TERMINAL_ENTRIES for entry in existing)
    for entry in new:
        check_sign(entry)
        if entry.order_id != order.id or entry.currency != order.currency:
            raise LedgerError("an entry must belong to the order and use its currency")
        if entry.idempotency_key in keys:
            raise LedgerError(f"{entry.idempotency_key} is already in the ledger")
        keys.add(entry.idempotency_key)
        if entry.entry_type in TERMINAL_ENTRIES:
            if terminal:
                raise LedgerError("an order is released or refunded at most once")
            terminal = True
        if entry.entry_type is EntryType.CAPTURE and entry.amount != order.captured_total:
            raise LedgerError("CAPTURE must equal the order's captured_total")
        if entry.entry_type is EntryType.FEE_RETAIN and entry.amount != -order.convenience_fee:
            raise LedgerError("FEE_RETAIN must equal the order's convenience fee")
    if balance([*existing, *new]) < 0:
        raise LedgerError("custody for an order can never go negative")


def check_settled(order: Order, entries: list[LedgerEntry]) -> None:
    """The IN_ESCROW invariant: CAPTURE, HOLD and FEE_RETAIN are present and what remains in
    custody is exactly the seller's future payout (captured_total - fee)."""
    types = [entry.entry_type for entry in entries]
    for required in (EntryType.CAPTURE, EntryType.HOLD):
        if required not in types:
            raise LedgerError(f"{required} row missing for order {order.id}")
    if order.convenience_fee > 0 and EntryType.FEE_RETAIN not in types:
        raise LedgerError(f"FEE_RETAIN row missing for order {order.id}")
    if balance(entries) != order.captured_total - order.convenience_fee:
        raise LedgerError("escrow balance must equal the seller's net payout")
