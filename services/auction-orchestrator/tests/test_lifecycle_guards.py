"""Rows A1-A8 of docs/state-machines.md, and everything outside them, refused (#24)."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from app.domain.auction import STATES
from app.domain.lifecycle import (
    EVENTS,
    SYSTEM,
    TRANSITIONS,
    Actor,
    GuardFailed,
    IllegalTransition,
    transition,
)
from tests.support import NOW, SELLER, draft

SELLER_ACTOR = Actor(user_id=SELLER)
ADMIN_ACTOR = Actor(user_id=uuid4(), is_admin=True)


def in_state(state: str, **overrides):
    return replace(draft(), state=state, **overrides)


def test_the_table_matches_the_published_state_machine():
    assert TRANSITIONS == {
        ("publish", "DRAFT"): "SCHEDULED",
        ("open", "SCHEDULED"): "OPEN",
        ("extend", "OPEN"): "EXTENDED",
        ("extend", "EXTENDED"): "EXTENDED",
        ("close", "OPEN"): "CLOSING",
        ("close", "EXTENDED"): "CLOSING",
        ("drained", "CLOSING"): "CLOSED",
        ("settle", "CLOSED"): "SETTLED",
        ("cancel", "DRAFT"): "CANCELLED",
        ("cancel", "SCHEDULED"): "CANCELLED",
    }


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("event", sorted(EVENTS))
def test_every_pair_outside_the_table_is_refused(state, event):
    if (event, state) in TRANSITIONS:
        return
    with pytest.raises(IllegalTransition) as error:
        transition(in_state(state), event, now=NOW, actor=ADMIN_ACTOR)
    assert (error.value.event, error.value.state) == (event, state)


@pytest.mark.parametrize("state", ["SETTLED", "CANCELLED"])
def test_terminal_states_are_final(state):
    for event in EVENTS:
        with pytest.raises(IllegalTransition):
            transition(in_state(state), event, now=NOW, actor=ADMIN_ACTOR)


def test_a1_publish_by_the_seller():
    published = transition(draft(), "publish", now=NOW, actor=SELLER_ACTOR)
    assert published.state == "SCHEDULED"
    assert published.original_closes_at == published.closes_at
    assert published.version == 2


@pytest.mark.parametrize("actor", [Actor(user_id=uuid4()), ADMIN_ACTOR, SYSTEM])
def test_a1_publish_by_anyone_else_is_forbidden(actor):
    with pytest.raises(GuardFailed) as error:
        transition(draft(), "publish", now=NOW, actor=actor)
    assert error.value.code == "FORBIDDEN"


@pytest.mark.parametrize(
    "overrides",
    [
        {"opens_at": None},
        {"closes_at": None},
        {"opens_at": NOW - timedelta(minutes=5)},
    ],
)
def test_a1_publish_validates_the_schedule(overrides):
    with pytest.raises(GuardFailed) as error:
        transition(replace(draft(), **overrides), "publish", now=NOW, actor=SELLER_ACTOR)
    assert (error.value.code, error.value.status) == ("VALIDATION_ERROR", 422)


def test_a1_tolerates_a_slightly_late_publish():
    late = replace(draft(), opens_at=NOW - timedelta(seconds=30))
    assert transition(late, "publish", now=NOW, actor=SELLER_ACTOR).state == "SCHEDULED"


def test_a2_open_waits_for_opens_at_unless_an_admin_forces_it():
    scheduled = in_state("SCHEDULED")
    with pytest.raises(GuardFailed) as error:
        transition(scheduled, "open", now=NOW, actor=SYSTEM)
    assert error.value.code == "CONFLICT"
    assert transition(scheduled, "open", now=scheduled.opens_at, actor=SYSTEM).state == "OPEN"
    assert transition(scheduled, "open", now=NOW, actor=ADMIN_ACTOR).state == "OPEN"


@pytest.mark.parametrize("event", ["open", "close", "drained", "extend", "settle"])
def test_platform_events_are_not_for_ordinary_users(event):
    state = {"open": "SCHEDULED", "close": "OPEN", "drained": "CLOSING", "extend": "OPEN",
             "settle": "CLOSED"}[event]
    with pytest.raises(GuardFailed) as error:
        transition(in_state(state), event, now=NOW, actor=SELLER_ACTOR)
    assert error.value.code == "FORBIDDEN"


def test_a4_extend_moves_closes_at_and_stops_at_the_cap():
    auction = in_state("OPEN")
    for count in range(1, auction.max_extensions + 1):
        auction = transition(auction, "extend", now=NOW, actor=SYSTEM)
        assert (auction.state, auction.extension_count) == ("EXTENDED", count)
    assert auction.closes_at == draft().closes_at + timedelta(seconds=120 * 10)
    with pytest.raises(GuardFailed) as error:
        transition(auction, "extend", now=NOW, actor=SYSTEM)
    assert error.value.details == {"max_extensions": 10}


def test_a5_close_waits_for_closes_at_and_starts_the_drain():
    auction = in_state("EXTENDED")
    with pytest.raises(GuardFailed):
        transition(auction, "close", now=NOW, actor=SYSTEM)
    closing = transition(auction, "close", now=auction.closes_at, actor=SYSTEM)
    assert (closing.state, closing.closing_since) == ("CLOSING", auction.closes_at)


def test_a6_drained_names_the_highest_server_seq_bid_as_winner():
    leader = uuid4()
    closed = transition(in_state("CLOSING", last_bid_seq=7, leading_bid_id=leader), "drained",
                        now=NOW, actor=SYSTEM)
    assert (closed.state, closed.winning_bid_id) == ("CLOSED", leader)
    no_bids = transition(in_state("CLOSING"), "drained", now=NOW, actor=SYSTEM)
    assert no_bids.winning_bid_id is None


def test_a7_settle_needs_a_winner():
    with pytest.raises(GuardFailed):
        transition(in_state("CLOSED"), "settle", now=NOW, actor=SYSTEM)
    settled = transition(in_state("CLOSED", winning_bid_id=uuid4()), "settle", now=NOW,
                         actor=SYSTEM)
    assert settled.state == "SETTLED"


def test_a8_cancel_by_seller_or_admin_before_any_bid():
    for actor in (SELLER_ACTOR, ADMIN_ACTOR):
        assert transition(in_state("SCHEDULED"), "cancel", now=NOW, actor=actor).state == \
            "CANCELLED"
    with pytest.raises(GuardFailed):
        transition(in_state("DRAFT"), "cancel", now=NOW, actor=Actor(user_id=uuid4()))
    with pytest.raises(GuardFailed) as error:
        transition(in_state("SCHEDULED", last_bid_seq=1), "cancel", now=NOW, actor=SELLER_ACTOR)
    assert error.value.code == "CONFLICT"
