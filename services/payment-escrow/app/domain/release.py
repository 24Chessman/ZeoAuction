"""Release execution for buyer-confirm, sweep-expiry and adjudication triggers (Plan 6, #65).

All three triggers converge on the same RELEASE ledger write:
    net = captured_total - convenience_fee (= winning_bid_amount)
with idempotency key:
    order:{id}:release

Guard R1 (docs/state-machines.md): no dispute in OPEN or UNDER_REVIEW exists.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.domain.ledger import (
    TERMINAL_ENTRIES,
    EntryType,
    LedgerEntry,
    LedgerError,
)
from app.domain.order_state import assert_not_terminal
from app.domain.orders import (
    IllegalOrderTransition,
    Order,
    confirm_receipt,
    sweep_expiry,
    adjudicate_seller,
)


class ReleaseTrigger(StrEnum):
    BUYER_CONFIRM = "confirm_receipt"
    SWEEP_EXPIRY = "sweep_expiry"
    ADJUDICATE_SELLER = "adjudicate_seller"


def build_release_entry(order: Order, *, note: str | None = None) -> LedgerEntry:
    """Build the single RELEASE ledger entry for an order payout."""
    net_payout = order.captured_total - order.convenience_fee
    if net_payout <= Decimal("0.00"):
        raise LedgerError(f"Net release payout must be positive, got {net_payout}")
    return LedgerEntry(
        order_id=order.id,
        entry_type=EntryType.RELEASE,
        amount=-net_payout,
        currency=order.currency,
        idempotency_key=order.idempotency_key("release"),
        saga_id=order.saga_id,
        note=note or "Escrow release to seller",
    )


def execute_release(
    order: Order,
    trigger: ReleaseTrigger | str,
    now: datetime,
    existing_ledger: Sequence[LedgerEntry] = (),
    *,
    has_open_dispute: bool = False,
) -> tuple[Order, LedgerEntry]:
    """Execute release logic: check guards, move order state, and return the RELEASE ledger entry.

    Guard R1: If an open dispute exists, release aborts.
    Database invariant: At most one terminal row (RELEASE / REFUND) per order.
    """
    assert_not_terminal(order, str(trigger))

    if has_open_dispute:
        raise IllegalOrderTransition(str(trigger), f"{order.state} with open dispute")

    # Guard terminal ledger rows
    for entry in existing_ledger:
        if entry.entry_type in TERMINAL_ENTRIES:
            raise LedgerError("an order is released or refunded at most once")

    trigger_val = ReleaseTrigger(trigger) if isinstance(trigger, str) else trigger

    if trigger_val == ReleaseTrigger.BUYER_CONFIRM:
        new_order = confirm_receipt(order, now)
        note = "Release trigger: buyer confirmation"
    elif trigger_val == ReleaseTrigger.SWEEP_EXPIRY:
        new_order = sweep_expiry(order, now)
        note = "Release trigger: protection window expired (sweep)"
    elif trigger_val == ReleaseTrigger.ADJUDICATE_SELLER:
        new_order = adjudicate_seller(order, now)
        note = "Release trigger: admin adjudication in seller favour"
    else:
        raise ValueError(f"Unknown release trigger: {trigger}")

    release_entry = build_release_entry(order, note=note)
    return new_order, release_entry
