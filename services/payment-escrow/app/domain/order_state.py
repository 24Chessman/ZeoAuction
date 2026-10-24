"""Terminal states and order state machine rules (Plan 6, #35; SDD 6.2, FR-AO-6).

Terminal states are final: RELEASED, REFUNDED and CANCELLED. After reaching a terminal state,
no subsequent transition or event is accepted, and any attempt raises IllegalOrderTransition.
"""

from app.domain.orders import (
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalOrderTransition,
    Order,
)


def is_terminal(state: str) -> bool:
    """Return True if the given state is one of the final terminal order states."""
    return state in TERMINAL_STATES


def assert_not_terminal(order: Order, event: str) -> None:
    """Refuse any event against an order in a terminal state (FR-AO-6)."""
    if order.is_terminal:
        raise IllegalOrderTransition(event, order.state)


def next_state(current_state: str, event: str) -> str:
    """Compute the next state or raise IllegalOrderTransition."""
    target = TRANSITIONS.get((event, current_state))
    if target is None:
        raise IllegalOrderTransition(event, current_state)
    return target
