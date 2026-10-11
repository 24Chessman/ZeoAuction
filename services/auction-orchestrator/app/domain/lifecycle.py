"""Auction lifecycle transition guards, rows A1-A8 of docs/state-machines.md (#24).

Pure logic, no I/O. This module is the single source of lifecycle truth: an event missing from
:data:`TRANSITIONS` for the current state raises :class:`IllegalTransition`; a listed event
whose guard does not hold raises :class:`GuardFailed` with the code the table names. Either
way nothing changes.

Who may cause each event:

* ``publish`` (A1): the seller. The JWT part of the guard (``kyc_status = VERIFIED``, not
  suspended) is the listing gate, applied to the route by ``zeo_common.gateway.VerifiedSeller``.
* ``open``, ``close``, ``drained`` (A2, A5, A6): the lifecycle timer. An administrator may
  force them early (an operator override, recorded with the admin as actor).
* ``extend`` (A4): the anti-snipe rule on an accepted bid (:mod:`app.domain.anti_snipe`).
* ``settle`` (A7): settlement (Plan 5), or an administrator.
* ``cancel`` (A8): the seller or an administrator, only before any bid.

A3 (``acceptBid``) does not change the auction row; Bid Processing asks CT-1 instead.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.domain.auction import Auction

# (event, from_state) -> to_state.
TRANSITIONS: dict[tuple[str, str], str] = {
    ("publish", "DRAFT"): "SCHEDULED",      # A1
    ("open", "SCHEDULED"): "OPEN",          # A2
    ("extend", "OPEN"): "EXTENDED",         # A4
    ("extend", "EXTENDED"): "EXTENDED",     # A4
    ("close", "OPEN"): "CLOSING",           # A5
    ("close", "EXTENDED"): "CLOSING",       # A5
    ("drained", "CLOSING"): "CLOSED",       # A6
    ("settle", "CLOSED"): "SETTLED",        # A7
    ("cancel", "DRAFT"): "CANCELLED",       # A8
    ("cancel", "SCHEDULED"): "CANCELLED",   # A8
}
EVENTS = frozenset(event for event, _ in TRANSITIONS)
SYSTEM_EVENTS = frozenset({"open", "extend", "close", "drained", "settle"})

# A publish whose opens_at slipped into the past by less than this (the seller pressed the
# button a moment late) is still accepted; the timer opens it on its next tick.
PUBLISH_CLOCK_SKEW = timedelta(seconds=60)


@dataclass(frozen=True)
class Actor:
    """Who causes a transition. ``user_id`` None means the platform itself (timer, consumer)."""

    user_id: UUID | None
    is_admin: bool = False

    @property
    def is_system(self) -> bool:
        return self.user_id is None


SYSTEM = Actor(user_id=None)


class IllegalTransition(Exception):
    def __init__(self, event: str, state: str) -> None:
        super().__init__(f"event {event!r} is not allowed from state {state}")
        self.event = event
        self.state = state


class GuardFailed(Exception):
    """The transition exists but its guard does not hold; maps to the table's error code."""

    def __init__(self, code: str, message: str, status: int,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def _forbidden(message: str) -> GuardFailed:
    return GuardFailed("FORBIDDEN", message, 403)


def _invalid(message: str) -> GuardFailed:
    return GuardFailed("VALIDATION_ERROR", message, 422)


def _check_actor(auction: Auction, event: str, actor: Actor) -> None:
    if event == "publish":
        if actor.user_id != auction.seller_id:
            raise _forbidden("Only the seller can publish this auction")
    elif event == "cancel":
        if not (actor.is_admin or actor.user_id == auction.seller_id):
            raise _forbidden("Only the seller or an administrator can cancel this auction")
    elif event in SYSTEM_EVENTS and not (actor.is_system or actor.is_admin):
        raise _forbidden(f"{event} is performed by the platform, not by users")


def _check_publish(auction: Auction, now: datetime) -> None:
    if auction.opens_at is None or auction.closes_at is None:
        raise _invalid("opens_at and closes_at are required to publish")
    if auction.opens_at < now - PUBLISH_CLOCK_SKEW:
        raise _invalid("opens_at is in the past")
    if auction.closes_at <= auction.opens_at:
        raise _invalid("closes_at must be after opens_at")


def _check_due(moment: datetime | None, now: datetime, what: str) -> None:
    if moment is None or moment > now:
        raise GuardFailed("CONFLICT", f"{what} has not been reached", 409,
                          {"due_at": None if moment is None else moment.isoformat()})


def transition(auction: Auction, event: str, *, now: datetime, actor: Actor) -> Auction:
    """Return the auction after ``event``, or raise. The caller persists it with the version
    check and records it in ``auction_state_transitions``."""
    to_state = TRANSITIONS.get((event, auction.state))
    if to_state is None:
        raise IllegalTransition(event, auction.state)
    _check_actor(auction, event, actor)
    # Administrators may force a timer event early; the platform only acts when it is due.
    timed = not actor.is_admin
    changes: dict[str, Any] = {}

    if event == "publish":
        _check_publish(auction, now)
        changes["original_closes_at"] = auction.closes_at
    elif event == "open":
        if timed:
            _check_due(auction.opens_at, now, "opens_at")
    elif event == "extend":
        if auction.closes_at is None or auction.extension_count >= auction.max_extensions:
            raise GuardFailed("CONFLICT", "The extension cap has been reached", 409,
                              {"max_extensions": auction.max_extensions})
        changes["extension_count"] = auction.extension_count + 1
        changes["closes_at"] = auction.closes_at + timedelta(seconds=auction.extension_seconds)
    elif event == "close":
        if timed:
            _check_due(auction.closes_at, now, "closes_at")
        changes["closing_since"] = now
    elif event == "drained":
        # The winner is the accepted bid with the highest server_seq (null if none).
        changes["winning_bid_id"] = auction.leading_bid_id
    elif event == "settle":
        if auction.winning_bid_id is None:
            raise GuardFailed("CONFLICT", "An auction without a winner cannot be settled", 409)
    elif event == "cancel" and auction.has_bids:
        raise GuardFailed("CONFLICT", "An auction with accepted bids cannot be cancelled", 409)

    return replace(auction, state=to_state, updated_at=now, version=auction.version + 1,
                   **changes)
