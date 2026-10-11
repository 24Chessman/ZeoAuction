from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tests.support import ADMIN, SELLER, admin_headers, bearer
from zeo_common.contract_testing import assert_matches_contract

CT1 = ("openapi/internal/auction-state.v1.yaml", "/components/schemas/AuctionState")


def test_create_returns_a_draft_owned_by_the_caller(harness):
    response = harness.create()
    assert response.status_code == 201
    auction = response.json()
    assert auction["state"] == "DRAFT"
    assert auction["seller_id"] == str(SELLER)
    assert auction["starting_price"] == "100.00"
    assert (auction["max_extensions"], auction["guard_interval_seconds"]) == (10, 120)


def test_a_seller_id_in_the_body_is_refused(harness):
    response = harness.create(seller_id=str(uuid4()))
    assert response.status_code == 422
    assert harness.repo.auctions == {}


def test_get_auction_is_public(harness):
    auction_id = harness.created()
    response = harness.client.get(f"/api/v1/auctions/{auction_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Vintage film camera"


def test_unknown_auction_is_404_with_envelope(harness):
    response = harness.client.get(f"/api/v1/auctions/{uuid4()}/state")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert_matches_contract(response.json(), "openapi/common.v1.yaml",
                            "/components/schemas/Error")


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "ab"},
        {"starting_price": 100.0},
        {"starting_price": "100.5"},
        {"reserve_price": "50.00"},
        {"category": "  "},
        {"currency": "usd"},
    ],
)
def test_invalid_auctions_are_rejected(harness, overrides):
    response = harness.create(**overrides)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_close_before_open_is_rejected(harness):
    now = datetime.now(UTC)
    response = harness.create(opens_at=now.isoformat(),
                              closes_at=(now - timedelta(hours=1)).isoformat())
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("events", "state", "permitted"),
    [
        ((), "DRAFT", False),
        (("publish",), "SCHEDULED", False),
        (("publish", "open"), "OPEN", True),
        (("publish", "open", "close"), "CLOSING", False),
        (("publish", "open", "close", "drained"), "CLOSED", False),
        (("cancel",), "CANCELLED", False),
    ],
)
def test_ct1_state_follows_the_lifecycle(harness, events, state, permitted):
    auction_id = harness.created()
    harness.drive(auction_id, *events)
    response = harness.client.get(f"/api/v1/auctions/{auction_id}/state")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == state
    assert body["bid_permitted"] is permitted
    assert body["seller_id"] == str(SELLER)
    assert_matches_contract(body, *CT1)


def test_publish_copies_the_close_time_and_publishes_an_event(harness):
    auction_id = harness.created()
    published = harness.drive(auction_id, "publish")
    assert published["original_closes_at"] == published["closes_at"]
    (event,) = harness.events.events
    assert (event["event"], event["from_state"], event["to_state"]) == (
        "publish", "DRAFT", "SCHEDULED")
    assert event["actor_id"] == str(SELLER)


def test_only_the_seller_can_publish(harness):
    auction_id = harness.created()
    response = harness.publish(auction_id, headers=bearer(uuid4()))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_publish_needs_both_times(harness):
    auction_id = harness.created(opens_at=None)
    response = harness.publish(auction_id)
    assert response.status_code == 422
    assert "opens_at" in response.json()["message"]


def test_publish_refuses_an_opening_time_in_the_past(harness):
    now = datetime.now(UTC)
    auction_id = harness.created(opens_at=(now - timedelta(hours=1)).isoformat())
    assert harness.publish(auction_id).status_code == 422


def test_seller_and_admin_can_cancel_but_others_cannot(harness):
    first = harness.created()
    stranger = harness.client.post(f"/api/v1/auctions/{first}/cancel", headers=bearer(uuid4()))
    assert stranger.status_code == 403
    by_admin = harness.client.post(f"/api/v1/auctions/{first}/cancel", headers=admin_headers())
    assert by_admin.json()["state"] == "CANCELLED"
    second = harness.created()
    harness.drive(second, "publish", "cancel")


def test_cancel_after_open_is_illegal(harness):
    auction_id = harness.created()
    harness.drive(auction_id, "publish", "open")
    response = harness.client.post(f"/api/v1/auctions/{auction_id}/cancel", headers=bearer())
    assert response.status_code == 409
    assert response.json()["details"] == {"state": "OPEN", "event": "cancel"}


def test_operator_events_need_an_admin(harness):
    auction_id = harness.created()
    harness.drive(auction_id, "publish")
    response = harness.client.post(f"/api/v1/auctions/{auction_id}/events",
                                   json={"event": "open"}, headers=bearer())
    assert response.status_code == 403


@pytest.mark.parametrize("event", ["publish", "cancel", "extend", "teleport"])
def test_user_events_are_not_operator_events(harness, event):
    auction_id = harness.created()
    assert harness.operate(auction_id, event).status_code == 422


def test_illegal_transition_is_refused_and_changes_nothing(harness):
    auction_id = harness.created()
    response = harness.operate(auction_id, "open")
    assert response.status_code == 409
    assert response.json()["details"] == {"state": "DRAFT", "event": "open"}
    assert harness.client.get(f"/api/v1/auctions/{auction_id}").json()["state"] == "DRAFT"
    assert harness.repo.lifecycle(UUID(auction_id)) == ["create"]
    assert harness.events.events == []


def test_terminal_states_accept_no_event(harness):
    auction_id = harness.created()
    harness.drive(auction_id, "cancel")
    for event in ("open", "close", "drained", "settle"):
        assert harness.operate(auction_id, event).status_code == 409
    assert harness.publish(auction_id).status_code == 409


def test_settle_needs_a_winner(harness):
    auction_id = harness.created()
    harness.drive(auction_id, "publish", "open", "close", "drained")
    response = harness.operate(auction_id, "settle")
    assert response.status_code == 409
    assert "winner" in response.json()["message"]


def test_transitions_are_recorded_with_actor(harness):
    auction_id = harness.created()
    harness.drive(auction_id, "publish", "open")
    rows = [row for row in harness.repo.transitions if str(row[0]) == auction_id]
    assert [(event, actor) for _, event, _, _, actor in rows] == [
        ("create", SELLER), ("publish", SELLER), ("open", ADMIN)]
