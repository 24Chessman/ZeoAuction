"""Per-order escrow ledger reconciliation against the invariants (Plan 6, #66; SDD 4.3.2).

Invariants asserted per order:
1. captured_total = winning_bid_amount + convenience_fee
2. Every terminal order (RELEASED, REFUNDED, CANCELLED) has rows that sum to exactly ZERO.
3. No order ever gets both a RELEASE and a REFUND row.
4. Non-terminal holding states (IN_ESCROW, SHIPPED, DISPUTED) have balance equal to
   the seller's net payout (captured_total - convenience_fee = winning_bid_amount).
5. Ledger sign conventions hold for every row.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from app.domain.ledger import (
    EntryType,
    LedgerEntry,
    ZERO,
    balance,
    check_sign,
)
from app.domain.orders import Order, TERMINAL_STATES


@dataclass(frozen=True)
class ReconciliationReport:
    order_id: UUID
    state: str
    is_valid: bool
    balance: Decimal
    errors: list[str] = field(default_factory=list)


def reconcile_order(order: Order, ledger: Sequence[LedgerEntry]) -> ReconciliationReport:
    """Run full reconciliation verification on an order and its ledger entries."""
    errors: list[str] = []

    # 1. captured_total invariant
    expected_captured = order.winning_bid_amount + order.convenience_fee
    if order.captured_total != expected_captured:
        errors.append(
            f"captured_total {order.captured_total} != winning_bid ({order.winning_bid_amount}) + "
            f"fee ({order.convenience_fee})"
        )

    # Check signs and order ownership of each ledger entry
    for entry in ledger:
        try:
            check_sign(entry)
        except Exception as e:
            errors.append(f"Sign convention error on entry {entry.idempotency_key}: {e}")
        if entry.order_id != order.id:
            errors.append(f"Entry {entry.idempotency_key} order_id {entry.order_id} != {order.id}")
        if entry.currency != order.currency:
            errors.append(f"Entry {entry.idempotency_key} currency {entry.currency} != {order.currency}")

    current_balance = balance(ledger)

    terminal_entries = [e for e in ledger if e.entry_type in (EntryType.RELEASE, EntryType.REFUND)]
    if len(terminal_entries) > 1:
        errors.append(
            f"Multiple terminal entries found ({len(terminal_entries)}): "
            f"{[e.entry_type.value for e in terminal_entries]}"
        )

    has_release = any(e.entry_type == EntryType.RELEASE for e in ledger)
    has_refund = any(e.entry_type == EntryType.REFUND for e in ledger)
    if has_release and has_refund:
        errors.append("Order has both RELEASE and REFUND entries")

    if order.state in TERMINAL_STATES:
        # Invariant 2: Terminal balance must equal exactly 0
        if current_balance != ZERO:
            errors.append(
                f"Terminal order in state {order.state} has non-zero balance: {current_balance}"
            )

        if order.state == "RELEASED":
            if not has_release:
                errors.append("RELEASED order is missing a RELEASE entry")
            else:
                release_row = next(e for e in ledger if e.entry_type == EntryType.RELEASE)
                net_expected = -(order.captured_total - order.convenience_fee)
                if release_row.amount != net_expected:
                    errors.append(
                        f"RELEASE amount {release_row.amount} != expected payout {net_expected}"
                    )

        elif order.state == "REFUNDED":
            if not has_refund:
                errors.append("REFUNDED order is missing a REFUND entry")
            else:
                refund_row = next(e for e in ledger if e.entry_type == EntryType.REFUND)
                # Either buyer fault (-winning_bid) or seller/platform fault (-captured_total)
                if refund_row.amount not in (-order.winning_bid_amount, -order.captured_total):
                    errors.append(
                        f"REFUND amount {refund_row.amount} matches neither winning_bid "
                        f"({-order.winning_bid_amount}) nor captured_total ({-order.captured_total})"
                    )

        elif order.state == "CANCELLED":
            # If cancelled before capture, balance is 0. If cancelled after capture (S2 comp), balance is 0.
            pass

    elif order.state in ("IN_ESCROW", "SHIPPED", "DISPUTED"):
        # Invariant 4: Held funds must equal seller's future net payout
        expected_balance = order.captured_total - order.convenience_fee
        if current_balance != expected_balance:
            errors.append(
                f"Custody balance {current_balance} != expected net payout {expected_balance}"
            )

    return ReconciliationReport(
        order_id=order.id,
        state=order.state,
        is_valid=len(errors) == 0,
        balance=current_balance,
        errors=errors,
    )
