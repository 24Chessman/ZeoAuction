"""Settlement over HTTP (#33, gate #106): close -> invoice -> Checkout -> capture -> escrow hold.

Uses the deterministic mock adapter, which follows the Razorpay flow of ADR-0009.
"""

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.domain import orders as machine
from app.payment_port.mock_adapter import MockPaymentAdapter
from app.payment_port.port import TransientPaymentError
from tests.support import (
    ADMIN,
    BUYER,
    INTERNAL,
    LOSER,
    SELLER,
    Harness,
    bearer,
    body_of,
    request,
)
from zeo_common.contract_testing import assert_matches_contract

ORDER_SCHEMA = ("openapi/payment.v1.yaml", "/components/schemas/Order")


# ---------------------------------------------------------------------- S1: open the order


def test_s1_opens_an_invoiced_order_for_the_winner(harness):
    req = request("1250.00")
    response = harness.open(req)
    assert response.status_code == 201
    body = response.json()
    assert_matches_contract(body, *ORDER_SCHEMA)
    assert (body["state"], body["buyer_id"], body["total"], body["convenience_fee"]) == (
        "INVOICED", str(BUYER), "1349.00", "99.00")
    assert body["invoice"]["total"] == "1349.00" and body["invoice"]["fee_version"] == "2026-10-v1"
    assert body["test_mode"] is True and "no real money" in body["notice"]
    assert harness.events.types() == ["INVOICED"]
    assert_matches_contract(harness.events.events[0], "events/settlement_step.v1.json")


def test_s1_is_idempotent_per_auction(harness):
    req = request()
    first = harness.open(req).json()
    again = harness.open(req, key="settle-key-2")
    assert again.status_code == 200 and again.json()["order_id"] == first["order_id"]
    assert len(harness.repo.orders) == len(harness.repo.invoices) == 1
    assert harness.events.types() == ["INVOICED"]


def test_s1_refuses_a_different_winner_for_a_settled_auction(harness):
    req = request()
    harness.opened(req)
    other = request(auction_id=req.auction_id)
    response = harness.open(other)
    assert response.status_code == 409 and response.json()["code"] == "SETTLEMENT_CONFLICT"


def test_s1_refuses_another_currency(harness):
    response = harness.open(request(currency="USD"))
    assert response.status_code == 422 and "settlement currency" in response.json()["message"]


def test_s1_is_internal_only(harness):
    req = body_of(request())
    for headers in ({}, {"X-Internal-Token": "wrong-token"}):
        response = harness.client.post("/api/v1/internal/orders", json=req,
                                       headers=headers | {"Idempotency-Key": "settle-key-1"})
        assert response.status_code == 401
    missing_key = harness.client.post("/api/v1/internal/orders", json=req, headers=INTERNAL)
    assert missing_key.status_code == 422


def test_losing_bidders_are_never_invoiced(harness):
    order = harness.opened()
    assert all(o.buyer_id == BUYER for o in harness.repo.orders.values())
    response = harness.client.get(f"/api/v1/orders/{order['order_id']}", headers=bearer(LOSER))
    assert response.status_code == 403
    assert harness.checkout(order["order_id"], user=LOSER).status_code == 403


# ---------------------------------------------------------------------- Checkout and capture


def test_winner_pays_and_the_order_is_held_in_escrow(harness):
    order = harness.opened()
    checkout = harness.checkout(order["order_id"])
    assert checkout.status_code == 200
    session = checkout.json()
    assert_matches_contract(session, "openapi/payment.v1.yaml", "/components/schemas/Checkout")
    assert (session["provider"], session["amount"], session["amount_minor"],
            session["currency"]) == ("mock", "1349.00", 134900, "INR")
    assert session["description"].startswith("Invoice ZA-")

    paid = harness.pay(order["order_id"], session)
    assert paid.status_code == 200, paid.text
    assert_matches_contract(paid.json(), *ORDER_SCHEMA)
    assert paid.json()["state"] == "IN_ESCROW"
    assert [(row["entry_type"], row["amount"]) for row in harness.ledger(order["order_id"])] == [
        ("CAPTURE", "1349.00"), ("HOLD", "0.00"), ("FEE_RETAIN", "-99.00")]
    assert harness.events.types() == ["INVOICED", "CAPTURED", "HELD"]
    for event in harness.events.events:
        assert_matches_contract(event, "events/settlement_step.v1.json")
    held = harness.events.events[-1]
    assert (held["gross"], held["fee"], held["net"]) == ("1349.00", "99.00", "1250.00")


def test_the_quoted_fee_equals_the_invoiced_fee(harness):
    quote = harness.client.get("/api/v1/fees/quote", params={"bid_amount": "1250.00"}).json()
    order = harness.opened(request("1250.00"))
    assert (quote["convenience_fee"], quote["total"], quote["fee_version"]) == (
        order["invoice"]["convenience_fee"], order["invoice"]["total"],
        order["invoice"]["fee_version"])


def test_checkout_is_reused_and_only_the_winner_may_open_it(harness):
    order = harness.opened()
    first = harness.checkout(order["order_id"]).json()
    assert harness.checkout(order["order_id"]).json()["provider_order_id"] == (
        first["provider_order_id"])
    assert harness.checkout(order["order_id"], user=SELLER).status_code == 403
    harness.pay(order["order_id"], first)
    again = harness.checkout(order["order_id"])
    assert again.status_code == 409 and again.json()["code"] == "ORDER_NOT_PAYABLE"
    assert again.json()["details"] == {"state": "IN_ESCROW"}


def test_a_forged_signature_moves_nothing(harness):
    order = harness.opened()
    response = harness.pay(order["order_id"], signature="0" * 64)
    assert response.status_code == 400 and response.json()["code"] == "PAYMENT_SIGNATURE_INVALID"
    assert harness.repo.orders[UUID(order["order_id"])].state == "INVOICED"
    assert harness.repo.entries == []


def test_a_payment_for_another_provider_order_is_refused(harness):
    order = harness.opened()
    checkout = harness.checkout(order["order_id"]).json()
    other = harness.opened()
    harness.checkout(other["order_id"])
    response = harness.pay(other["order_id"], checkout)
    assert response.status_code == 400
    before_checkout = harness.opened()
    response = harness.pay(before_checkout["order_id"], checkout)
    assert response.json()["code"] == "PAYMENT_SIGNATURE_INVALID"


def test_paying_twice_captures_once(harness):
    order = harness.opened()
    checkout = harness.checkout(order["order_id"]).json()
    assert harness.pay(order["order_id"], checkout).json()["state"] == "IN_ESCROW"
    assert harness.pay(order["order_id"], checkout).json()["state"] == "IN_ESCROW"
    assert harness.port.calls.count(("capture", f"order:{order['order_id']}:capture")) == 1
    assert len(harness.repo.entries) == 3


def test_parties_and_admins_can_read_the_order(harness):
    order = harness.opened()
    for user, role in ((BUYER, "USER"), (SELLER, "USER"), (ADMIN, "ADMIN")):
        response = harness.client.get(f"/api/v1/auctions/{order['auction_id']}/order",
                                      headers=bearer(user, role=role))
        assert response.status_code == 200 and response.json()["order_id"] == order["order_id"]
    assert harness.client.get(f"/api/v1/auctions/{uuid4()}/order",
                              headers=bearer()).status_code == 404
    assert harness.client.get(f"/api/v1/orders/{uuid4()}", headers=bearer()).status_code == 404
    assert harness.client.get(f"/api/v1/orders/{order['order_id']}").status_code == 401


def test_the_ledger_is_for_administrators(harness):
    order = harness.opened()
    response = harness.client.get(f"/api/v1/orders/{order['order_id']}/ledger", headers=bearer())
    assert response.status_code == 403
    assert harness.ledger(order["order_id"]) == []


# ---------------------------------------------------------------------- webhooks


def webhook(harness, order, event_type="payment.authorized", event_id="evt_1", amount=None):
    """What Razorpay sends once the winner has paid in Checkout."""
    if harness.repo.orders[UUID(order["order_id"])].provider_order_id is None:
        harness.checkout(order["order_id"])
    provider_order_id = harness.repo.orders[UUID(order["order_id"])].provider_order_id
    payment_id = MockPaymentAdapter.payment_ref(provider_order_id)
    payload, headers = harness.port.webhook(
        event_type, provider_order_id, payment_id, Decimal(amount or order["total"]), "INR",
        event_id)
    return harness.client.post("/api/v1/webhooks/mock", content=payload, headers=headers)


def test_the_authorized_webhook_settles_without_the_browser(harness):
    order = harness.opened()
    response = webhook(harness, order)
    assert response.status_code == 200 and response.json() == {"outcome": "applied"}
    assert harness.repo.orders[UUID(order["order_id"])].state == "IN_ESCROW"


def test_redelivered_webhooks_are_deduplicated(harness):
    order = harness.opened()
    webhook(harness, order)
    assert webhook(harness, order).json() == {"outcome": "duplicate"}
    assert len(harness.repo.entries) == 3


def test_browser_and_webhook_converge_on_one_capture(harness):
    order = harness.opened()
    harness.pay(order["order_id"])
    assert webhook(harness, order, event_id="evt_late").json() == {"outcome": "applied"}
    assert harness.repo.orders[UUID(order["order_id"])].state == "IN_ESCROW"
    assert len(harness.repo.entries) == 3


@pytest.mark.parametrize("event_type, amount, outcome", [
    ("payment.failed", None, "ignored"),
    ("refund.processed", None, "ignored"),
    ("payment.authorized", "1.00", "ignored"),  # amount does not match the order
])
def test_other_webhooks_are_acknowledged_and_ignored(harness, event_type, amount, outcome):
    order = harness.opened()
    assert webhook(harness, order, event_type, amount=amount).json() == {"outcome": outcome}
    assert harness.repo.orders[UUID(order["order_id"])].state == "INVOICED"


def test_webhook_for_an_unknown_order_is_ignored(harness):
    payload, headers = harness.port.webhook("payment.authorized", "mock_order_x", "mock_pay_x",
                                            Decimal("1.00"), "INR", "evt_x")
    response = harness.client.post("/api/v1/webhooks/mock", content=payload, headers=headers)
    assert response.json() == {"outcome": "ignored"}


def test_unsigned_webhooks_and_other_providers_are_refused(harness):
    response = harness.client.post("/api/v1/webhooks/mock", content=b"{}",
                                   headers={"X-Mock-Signature": "0" * 64})
    assert response.status_code == 400 and response.json()["code"] == "WEBHOOK_SIGNATURE_INVALID"
    assert harness.client.post("/api/v1/webhooks/razorpay", content=b"{}").status_code == 404


# ---------------------------------------------------------------------- failures


def test_payment_down_parks_the_order_then_it_recovers(harness):
    """Gate #106: payment down -> AWAITING_CAPTURE_RETRY -> recovers with the same key."""
    order = harness.opened()
    key = f"order:{order['order_id']}:capture"
    harness.port._transient[key] = 4
    paid = harness.pay(order["order_id"])
    assert paid.json()["state"] == "AWAITING_CAPTURE_RETRY"
    assert harness.events.types() == ["INVOICED"]

    for _ in range(5):
        harness.clock.advance(seconds=31)
        asyncio.run(harness.service.run_due_work())
    stored = harness.repo.orders[UUID(order["order_id"])]
    assert stored.state == "IN_ESCROW"
    assert {k for _, k in harness.port.calls} == {key}
    assert harness.events.types() == ["INVOICED", "CAPTURED", "HELD"]


def test_the_breaker_opens_after_three_failures_and_fails_fast(harness):
    orders = [harness.opened() for _ in range(4)]
    for order in orders:
        harness.port._transient[f"order:{order['order_id']}:capture"] = 99
    states = [harness.pay(order["order_id"]).json()["state"] for order in orders]
    assert states == ["AWAITING_CAPTURE_RETRY"] * 4
    # The fourth capture never reached the provider: the breaker was open.
    assert len([c for c in harness.port.calls if c[0] == "capture"]) == 3
    assert harness.service.breaker.state == "open"


def test_a_declined_capture_compensates_s1(harness):
    order = harness.opened(request("1250.13"))  # total 1349.13: the mock declines .13
    response = harness.pay(order["order_id"])
    assert response.json()["state"] == "CANCELLED"
    assert response.json()["invoice"]["voided_at"] is not None
    assert harness.repo.entries == []
    assert harness.events.types() == ["INVOICED", "COMPENSATED"]


def test_an_unpaid_order_is_cancelled_after_the_payment_window(harness):
    order = harness.opened()
    harness.clock.advance(hours=47)
    assert asyncio.run(harness.service.run_due_work()) == []
    harness.clock.advance(hours=2)
    assert asyncio.run(harness.service.run_due_work()) == [(UUID(order["order_id"]),
                                                            "CANCELLED")]
    assert harness.checkout(order["order_id"]).json()["code"] == "ORDER_NOT_PAYABLE"


def test_a_capture_interrupted_by_a_crash_is_resumed(harness):
    order = harness.opened()
    checkout = harness.checkout(order["order_id"]).json()
    order_id = UUID(order["order_id"])
    stored = harness.repo.orders[order_id]
    harness.repo.orders[order_id] = machine.authorize(
        stored, checkout["simulated_payment"]["payment_id"], harness.clock())
    harness.clock.advance(minutes=1)
    assert asyncio.run(harness.service.run_due_work()) == []
    harness.clock.advance(minutes=2)
    assert asyncio.run(harness.service.run_due_work()) == [(order_id, "IN_ESCROW")]


def test_checkout_reports_a_provider_outage():
    class Down(MockPaymentAdapter):
        async def create_checkout(self, *args):
            raise TransientPaymentError("down")

    harness = Harness(port=Down())
    order = harness.opened()
    response = harness.checkout(order["order_id"])
    assert response.status_code == 503 and response.json()["code"] == (
        "PAYMENT_PROVIDER_UNAVAILABLE")


def test_a_broker_outage_does_not_undo_a_step(harness):
    harness.events.fail_next = True
    order = harness.opened()
    assert order["state"] == "INVOICED" and harness.events.types() == []
    assert "payment_events_publish_failures_total 1.0" in harness.client.get("/metrics").text
