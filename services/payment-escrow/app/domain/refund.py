"""Refund execution with fee treatment by fault (Plan 6, #66; SDD Table 6.3).

Fault determines the fee treatment:
- BUYER: fee is retained; buyer receives winning_bid only.
    Row: REFUND -winning_bid
- SELLER or PLATFORM: fee is refunded; buyer receives captured_total in full.
    Rows: COMPENSATION +fee (reverses FEE_RETAIN), REFUND -captured_total
"""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from app.domain.ledger import (
    TERMINAL_ENTRIES,
    EntryType,
    LedgerEntry,
    LedgerError,
)
from app.domain.order_state import assert_not_terminal
from app.domain.orders import (
    Order,
    adjudicate_buyer,
)


class Fault(StrEnum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    PLATFORM = "PLATFORM"


class RefundError(ValueError):
    pass


def build_refund_entries(
    order: Order,
    fault: Fault | str,
    existing_ledger: Sequence[LedgerEntry] = (),
    *,
    note: str | None = None,
) -> list[LedgerEntry]:
    """Construct ledger entries for a refund according to fault fee treatment."""
    fault_val = Fault(fault) if isinstance(fault, str) else fault

    # Check for existing terminal entries
    for entry in existing_ledger:
        if entry.entry_type in TERMINAL_ENTRIES:
            raise LedgerError("an order is released or refunded at most once")

    entries: list[LedgerEntry] = []

    if fault_val == Fault.BUYER:
        # Fee is retained by platform; buyer gets winning bid only
        entries.append(
            LedgerEntry(
                order_id=order.id,
                entry_type=EntryType.REFUND,
                amount=-order.winning_bid_amount,
                currency=order.currency,
                idempotency_key=order.idempotency_key("refund"),
                saga_id=order.saga_id,
                note=note or f"Refund to buyer (fault: {fault_val.value}; fee retained)",
            )
        )
    elif fault_val in (Fault.SELLER, Fault.PLATFORM):
        # Platform/seller at fault: refund convenience fee to custody, then refund all to buyer
        fee_entry = next(
            (e for e in existing_ledger if e.entry_type == EntryType.FEE_RETAIN),
            None,
        )
        compensates_id = (
            fee_entry.id if (fee_entry is not None and fee_entry.id is not None) else 1
        )

        if order.convenience_fee > 0:
            entries.append(
                LedgerEntry(
                    order_id=order.id,
                    entry_type=EntryType.COMPENSATION,
                    amount=order.convenience_fee,
                    currency=order.currency,
                    idempotency_key=order.idempotency_key("compensate-fee"),
                    saga_id=order.saga_id,
                    compensates_id=compensates_id,
                    note=f"Reverse FEE_RETAIN on {fault_val.value} fault",
                )
            )

        entries.append(
            LedgerEntry(
                order_id=order.id,
                entry_type=EntryType.REFUND,
                amount=-order.captured_total,
                currency=order.currency,
                idempotency_key=order.idempotency_key("refund"),
                saga_id=order.saga_id,
                note=note or f"Full refund to buyer (fault: {fault_val.value})",
            )
        )
    else:
        raise RefundError(f"Unsupported fault: {fault}")

    return entries


def execute_refund(
    order: Order,
    fault: Fault | str,
    now: datetime,
    existing_ledger: Sequence[LedgerEntry] = (),
    *,
    note: str | None = None,
) -> tuple[Order, list[LedgerEntry]]:
    """Execute refund transition: assert guards, advance state to REFUNDED, build ledger rows."""
    assert_not_terminal(order, "adjudicateBuyer")

    entries = build_refund_entries(order, fault, existing_ledger, note=note)
    new_order = adjudicate_buyer(order, now)
    return new_order, entries
