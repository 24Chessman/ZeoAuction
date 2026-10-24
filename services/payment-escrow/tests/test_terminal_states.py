"""Tests for terminal transitions and state enforcement (Plan 6, #35; FR-AO-6).

RELEASED, REFUNDED and CANCELLED are terminal states:
- Once an order reaches a terminal state, all subsequent events are refused.
- No new dispute can be opened against a terminal order.
- No second release or refund can be performed.
"""

from dataclasses import replace
from datetime import timedelta
import pytest

from app.domain.order_state import is_terminal, assert_not_terminal
from app.domain.orders import (
    IllegalOrderTransition,
    Order,
    confirm_receipt,
    mark_shipped,
    raise_dispute,
)
from app.main import build_app
from fastapi.testclient import TestClient

from tests.support import (
    BUYER,
    Clock,
    INTERNAL,
    NOW,
    SELLER,
    SETTINGS,
    bearer,
    order as make_order,
)
from tests.test_release import _setup_held_order


def test_is_terminal():
    assert is_terminal("RELEASED") is True
    assert is_terminal("REFUNDED") is True
    assert is_terminal("CANCELLED") is True
    assert is_terminal("INVOICED") is False
    assert is_terminal("CAPTURED") is False
    assert is_terminal("IN_ESCROW") is False
    assert is_terminal("SHIPPED") is False
    assert is_terminal("DISPUTED") is False


def test_terminal_order_refuses_events():
    base = make_order("1000.00")
    released = replace(base, state="RELEASED")
    refunded = replace(base, state="REFUNDED")
    cancelled = replace(base, state="CANCELLED")

    for terminal in (released, refunded, cancelled):
        assert terminal.is_terminal is True
        with pytest.raises(IllegalOrderTransition):
            assert_not_terminal(terminal, "any_event")
        with pytest.raises(IllegalOrderTransition):
            confirm_receipt(terminal, NOW)
        with pytest.raises(IllegalOrderTransition):
            mark_shipped(terminal, NOW)
        with pytest.raises(IllegalOrderTransition):
            raise_dispute(terminal, NOW)


def test_api_released_order_refuses_later_dispute(harness):
    order_id = _setup_held_order(harness, "1200.00")

    # Ship and confirm
    harness.client.post(f"/api/v1/orders/{order_id}/ship", headers=bearer(SELLER))
    harness.client.post(f"/api/v1/orders/{order_id}/confirm-receipt", headers=bearer(BUYER))

    # Order is now RELEASED
    # Attempt to freeze / dispute must be refused
    freeze_res = harness.client.post(f"/api/v1/internal/orders/{order_id}/freeze", headers=INTERNAL)
    assert freeze_res.status_code == 409
