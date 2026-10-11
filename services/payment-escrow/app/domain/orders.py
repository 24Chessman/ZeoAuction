"""Order settlement state machine, section 2 of docs/state-machines.md (O1-O5, #33).

Pure logic, no I/O. ADR-0009 put the buyer in the loop: with Razorpay the winner authorises
the payment in Checkout, so the forward path is

    INVOICED --authorize--> AUTHORIZED --capture--> CAPTURED --hold--> IN_ESCROW

A capture that fails transiently (provider outage, breaker open) parks the order in
AWAITING_CAPTURE_RETRY, from which the retrier captures again with the **same** idempotency key;
settlement is deferred, never abandoned. A definitive failure compensates S1 (O4): the order is
CANCELLED and its invoice voided, so no partial settlement remains.

An event missing from :data:`TRANSITIONS` for the current state raises
:class:`IllegalOrderTransition` and nothing changes (state-machine rule 1). Every function
returns a new :class:`Order` with ``version`` bumped; the repository saves it with the version
check (rule 3).
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.fees import FeeConfig

STATES = ("INVOICED", "AUTHORIZED", "AWAITING_CAPTURE_RETRY", "CAPTURED", "IN_ESCROW",
          "SHIPPED", "DISPUTED", "RELEASED", "REFUNDED", "CANCELLED")
TERMINAL_STATES = frozenset({"RELEASED", "REFUNDED", "CANCELLED"})
# The buyer can still (re)open Checkout: Razorpay accepts several attempts on one order.
PAYABLE_STATES = frozenset({"INVOICED"})
CAPTURABLE_STATES = frozenset({"AUTHORIZED", "AWAITING_CAPTURE_RETRY"})

# (event, from_state) -> to_state.
TRANSITIONS: dict[tuple[str, str], str] = {
    ("authorize", "INVOICED"): "AUTHORIZED",                            # buyer paid in Checkout
    ("capture", "AUTHORIZED"): "CAPTURED",                              # O2 (S2)
    ("capture", "AWAITING_CAPTURE_RETRY"): "CAPTURED",                  # O2 (S2)
    ("captureFailed", "AUTHORIZED"): "AWAITING_CAPTURE_RETRY",          # O3
    ("captureFailed", "AWAITING_CAPTURE_RETRY"): "AWAITING_CAPTURE_RETRY",  # O3, again
    ("compensateS1", "INVOICED"): "CANCELLED",                          # O4
    ("compensateS1", "AUTHORIZED"): "CANCELLED",                        # O4
    ("compensateS1", "AWAITING_CAPTURE_RETRY"): "CANCELLED",            # O4
    ("hold", "CAPTURED"): "IN_ESCROW",                                  # O5 (S3, S4)
}

MAX_CAPTURE_BACKOFF = timedelta(minutes=5)


class IllegalOrderTransition(Exception):
    def __init__(self, event: str, state: str) -> None:
        super().__init__(f"event {event!r} is not allowed from order state {state}")
        self.event = event
        self.state = state


class OrderValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SettlementRequest:
    """What Auction Orchestration sends once an auction is CLOSED with a winner (S1)."""

    auction_id: UUID
    buyer_id: UUID
    seller_id: UUID
    winning_bid_id: UUID
    winning_bid_amount: Decimal
    currency: str


@dataclass(frozen=True)
class Order:
    id: UUID
    auction_id: UUID
    buyer_id: UUID
    seller_id: UUID
    winning_bid_id: UUID
    winning_bid_amount: Decimal
    convenience_fee: Decimal
    captured_total: Decimal
    currency: str
    fee_version: str
    state: str
    saga_id: UUID
    provider: str
    created_at: datetime
    updated_at: datetime
    version: int = 1
    provider_order_id: str | None = None
    provider_payment_id: str | None = None
    capture_ref: str | None = None
    payment_due_at: datetime | None = None
    authorized_at: datetime | None = None
    capture_attempts: int = 0
    next_capture_at: datetime | None = None
    shipped_at: datetime | None = None
    protection_window_ends_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def idempotency_key(self, operation: str) -> str:
        """``order:{id}:{operation}`` (SDD 5.2.3): one key per money movement of an order."""
        return f"order:{self.id}:{operation}"

    def party(self, user_id: UUID) -> str | None:
        if user_id == self.buyer_id:
            return "buyer"
        if user_id == self.seller_id:
            return "seller"
        return None


def open_order(
    request: SettlementRequest, *, order_id: UUID, saga_id: UUID, fee: FeeConfig,
    provider: str, now: datetime, payment_window: timedelta,
) -> Order:
    """O1: the order for the winning bid only, stamped with the active ``fee_version``.

    Losing bidders are never invoiced (AC-09): the only buyer an order can have is the winner
    Auction Orchestration names, and ``payment.orders.auction_id`` is unique.
    """
    if not isinstance(request.winning_bid_amount, Decimal) or request.winning_bid_amount <= 0:
        raise OrderValidationError("winning_bid_amount must be a positive amount")
    if request.currency != fee.currency:
        raise OrderValidationError(
            f"auction currency {request.currency} differs from the settlement currency "
            f"{fee.currency}")
    if request.buyer_id == request.seller_id:
        raise OrderValidationError("the seller cannot buy their own auction")
    return Order(
        id=order_id, auction_id=request.auction_id, buyer_id=request.buyer_id,
        seller_id=request.seller_id, winning_bid_id=request.winning_bid_id,
        winning_bid_amount=request.winning_bid_amount, convenience_fee=fee.convenience_fee,
        captured_total=request.winning_bid_amount + fee.convenience_fee,
        currency=fee.currency, fee_version=fee.fee_version, state="INVOICED",
        saga_id=saga_id, provider=provider, created_at=now, updated_at=now,
        payment_due_at=now + payment_window,
    )


def _move(order: Order, event: str, now: datetime, **changes: Any) -> Order:
    to_state = TRANSITIONS.get((event, order.state))
    if to_state is None:
        raise IllegalOrderTransition(event, order.state)
    return replace(order, state=to_state, updated_at=now, version=order.version + 1, **changes)


def attach_checkout(order: Order, provider_order_id: str, now: datetime) -> Order:
    """Remember the provider order the buyer pays; created once and reused on every retry."""
    if order.state not in PAYABLE_STATES:
        raise IllegalOrderTransition("checkout", order.state)
    if order.provider_order_id not in (None, provider_order_id):
        raise OrderValidationError("the order already has a different provider order")
    return replace(order, provider_order_id=provider_order_id, updated_at=now,
                   version=order.version + 1)


def authorize(order: Order, payment_id: str, now: datetime) -> Order:
    if not payment_id:
        raise OrderValidationError("payment_id is required")
    return _move(order, "authorize", now, provider_payment_id=payment_id, authorized_at=now)


def capture_succeeded(order: Order, capture_ref: str, now: datetime) -> Order:
    return _move(order, "capture", now, capture_ref=capture_ref, next_capture_at=None,
                 capture_attempts=order.capture_attempts + 1)


def capture_backoff(attempts: int) -> timedelta:
    """1 s, 2 s, 4 s ... capped at five minutes; retried for as long as it takes."""
    return min(timedelta(seconds=2 ** min(attempts - 1, 16)), MAX_CAPTURE_BACKOFF)


def capture_failed(order: Order, now: datetime) -> Order:
    attempts = order.capture_attempts + 1
    return _move(order, "captureFailed", now, capture_attempts=attempts,
                 next_capture_at=now + capture_backoff(attempts))


def hold(order: Order, now: datetime) -> Order:
    return _move(order, "hold", now)


def cancel(order: Order, now: datetime) -> Order:
    return _move(order, "compensateS1", now, next_capture_at=None)
