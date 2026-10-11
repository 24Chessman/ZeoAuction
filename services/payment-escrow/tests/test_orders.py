"""Order state machine, docs/state-machines.md section 2 (O1-O5 with the Checkout step)."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain import orders as machine
from app.domain.fees import ACTIVE_FEE
from app.domain.orders import (
    STATES,
    TRANSITIONS,
    IllegalOrderTransition,
    OrderValidationError,
    capture_backoff,
)
from tests.support import BUYER, NOW, SELLER, order, request


def open_with(req):
    return machine.open_order(req, order_id=uuid4(), saga_id=uuid4(), fee=ACTIVE_FEE,
                              provider="mock", now=NOW, payment_window=timedelta(hours=48))


def test_o1_invoices_the_winning_bid_plus_the_flat_fee():
    opened = order("1250.00")
    assert opened.state == "INVOICED"
    assert opened.captured_total == Decimal("1349.00")
    assert (opened.convenience_fee, opened.fee_version, opened.currency) == (
        Decimal("99.00"), "2026-10-v1", "INR")
    assert opened.payment_due_at == NOW + timedelta(hours=48)
    assert opened.party(BUYER) == "buyer" and opened.party(SELLER) == "seller"
    assert opened.party(uuid4()) is None


@pytest.mark.parametrize("overrides, message", [
    ({"currency": "USD"}, "settlement currency"),
    ({"buyer_id": SELLER}, "own auction"),
    ({"winning_bid_amount": Decimal("0.00")}, "positive"),
])
def test_o1_guards(overrides, message):
    with pytest.raises(OrderValidationError, match=message):
        open_with(request(**overrides))


def test_forward_path_to_escrow():
    o = machine.attach_checkout(order(), "order_ABC", NOW)
    assert (o.provider_order_id, o.state, o.version) == ("order_ABC", "INVOICED", 2)
    o = machine.authorize(o, "pay_1", NOW)
    assert (o.state, o.provider_payment_id, o.authorized_at) == ("AUTHORIZED", "pay_1", NOW)
    o = machine.capture_succeeded(o, "pay_1", NOW)
    assert (o.state, o.capture_ref, o.capture_attempts) == ("CAPTURED", "pay_1", 1)
    o = machine.hold(o, NOW)
    assert o.state == "IN_ESCROW" and o.version == 5


def test_capture_failure_parks_and_backs_off_then_recovers():
    o = machine.authorize(order(), "pay_1", NOW)
    o = machine.capture_failed(o, NOW)
    assert (o.state, o.capture_attempts, o.next_capture_at) == (
        "AWAITING_CAPTURE_RETRY", 1, NOW + timedelta(seconds=1))
    o = machine.capture_failed(o, NOW)
    assert o.next_capture_at == NOW + timedelta(seconds=2)
    o = machine.capture_succeeded(o, "pay_1", NOW)
    assert (o.state, o.next_capture_at, o.capture_attempts) == ("CAPTURED", None, 3)


def test_backoff_is_capped():
    assert capture_backoff(1) == timedelta(seconds=1)
    assert capture_backoff(4) == timedelta(seconds=8)
    assert capture_backoff(50) == timedelta(minutes=5)


@pytest.mark.parametrize("state", ["INVOICED", "AUTHORIZED", "AWAITING_CAPTURE_RETRY"])
def test_o4_compensation_cancels_before_capture(state):
    o = order()
    if state != "INVOICED":
        o = machine.authorize(o, "pay_1", NOW)
    if state == "AWAITING_CAPTURE_RETRY":
        o = machine.capture_failed(o, NOW)
    assert machine.cancel(o, NOW).state == "CANCELLED"


def test_illegal_transitions_are_refused():
    held = machine.hold(machine.capture_succeeded(machine.authorize(order(), "p", NOW), "p",
                                                  NOW), NOW)
    for step in (lambda o: machine.authorize(o, "p2", NOW), lambda o: machine.cancel(o, NOW),
                 lambda o: machine.capture_failed(o, NOW), lambda o: machine.hold(o, NOW)):
        with pytest.raises(IllegalOrderTransition):
            step(held)
    with pytest.raises(IllegalOrderTransition):
        machine.capture_succeeded(order(), "p", NOW)  # never capture before authorisation
    with pytest.raises(IllegalOrderTransition):
        machine.attach_checkout(held, "order_X", NOW)


def test_a_provider_order_is_attached_once():
    o = machine.attach_checkout(order(), "order_ABC", NOW)
    assert machine.attach_checkout(o, "order_ABC", NOW).provider_order_id == "order_ABC"
    with pytest.raises(OrderValidationError):
        machine.attach_checkout(o, "order_OTHER", NOW)
    with pytest.raises(OrderValidationError):
        machine.authorize(o, "", NOW)


def test_terminal_states_accept_nothing():
    cancelled = machine.cancel(order(), NOW)
    assert cancelled.is_terminal
    assert not any(from_state in machine.TERMINAL_STATES for _, from_state in TRANSITIONS)
    assert set(to for to in TRANSITIONS.values()) <= set(STATES)


def test_idempotency_keys_are_per_order_and_operation():
    o = order()
    assert o.idempotency_key("capture") == f"order:{o.id}:capture"
