"""Provider webhooks have exactly one effect however they are delivered (#64, FR-PAY-7).

Two guards make that true. The ``(provider, event_id)`` record turns a redelivery of an event
already processed into a no-op. The order state machine and the per-operation idempotency key
(``order:{id}:capture``) make a *different* event about the same payment, a concurrent
duplicate, or a delivery retried after a crash converge on the one capture.
"""

import asyncio
from decimal import Decimal
from uuid import UUID

from app.domain.ledger import EntryType
from app.payment_port.mock_adapter import MockPaymentAdapter
from tests.support import Harness


def delivery(harness: Harness, order: dict, *, event_id: str = "evt_1",
             event_type: str = "payment.authorized") -> tuple[bytes, dict]:
    if harness.repo.orders[UUID(order["order_id"])].provider_order_id is None:
        harness.checkout(order["order_id"])
    provider_order_id = harness.repo.orders[UUID(order["order_id"])].provider_order_id
    return harness.port.webhook(event_type, provider_order_id,
                                MockPaymentAdapter.payment_ref(provider_order_id),
                                Decimal(order["total"]), "INR", event_id)


def post(harness: Harness, payload: bytes, headers: dict) -> str:
    response = harness.client.post("/api/v1/webhooks/mock", content=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["outcome"]


def captures(harness: Harness, order_id: UUID) -> int:
    rows = asyncio.run(harness.repo.ledger(order_id))
    return sum(1 for row in rows if row.entry_type is EntryType.CAPTURE)


def provider_captures(harness: Harness) -> int:
    return len({key for op, key in harness.port.calls if op == "capture"})


def test_the_same_delivery_three_times_has_one_effect(harness):
    order = harness.opened()
    payload, headers = delivery(harness, order)
    assert [post(harness, payload, headers) for _ in range(3)] == [
        "applied", "duplicate", "duplicate"]
    order_id = UUID(order["order_id"])
    assert captures(harness, order_id) == 1 and provider_captures(harness) == 1
    assert harness.events.types(order_id) == ["INVOICED", "CAPTURED", "HELD"]
    metrics = harness.client.get("/metrics").text
    assert 'payment_webhooks_total{outcome="duplicate",provider="mock"} 2.0' in metrics


def test_different_events_about_one_payment_capture_once(harness):
    order = harness.opened()
    authorized = delivery(harness, order, event_id="evt_auth")
    captured = delivery(harness, order, event_id="evt_capt", event_type="payment.captured")
    resent = delivery(harness, order, event_id="evt_auth_resent")
    for payload, headers in (authorized, captured, resent):
        assert post(harness, payload, headers) == "applied"  # verified and acted on ...
    order_id = UUID(order["order_id"])
    assert captures(harness, order_id) == 1  # ... but only the first moved money
    assert provider_captures(harness) == 1


def test_concurrent_duplicates_converge_on_one_capture(harness):
    order = harness.opened()
    payload, headers = delivery(harness, order)
    service = harness.service

    async def both():
        return await asyncio.gather(service.handle_webhook("mock", payload, headers),
                                    service.handle_webhook("mock", payload, headers))

    outcomes = asyncio.run(both())
    assert sorted(outcomes) in (["applied", "applied"], ["applied", "duplicate"])
    order_id = UUID(order["order_id"])
    assert harness.repo.orders[order_id].state == "IN_ESCROW"
    assert captures(harness, order_id) == 1 and provider_captures(harness) == 1


def test_a_delivery_interrupted_before_it_was_marked_processed_is_safely_redone():
    harness = Harness()
    order = harness.opened()
    payload, headers = delivery(harness, order)
    original = harness.repo.mark_event_processed

    async def crash(event, now):
        raise ConnectionError("crashed before marking the event processed")

    harness.repo.mark_event_processed = crash
    response = harness.client.post("/api/v1/webhooks/mock", content=payload, headers=headers)
    assert response.status_code == 500  # the provider will redeliver
    harness.repo.mark_event_processed = original
    assert post(harness, payload, headers) == "applied"  # re-run, but the order is settled
    assert post(harness, payload, headers) == "duplicate"
    order_id = UUID(order["order_id"])
    assert captures(harness, order_id) == 1 and provider_captures(harness) == 1


def test_a_webhook_after_the_browser_paid_is_a_no_op(harness):
    order = harness.opened()
    harness.pay(order["order_id"])
    payload, headers = delivery(harness, order, event_id="evt_after_browser")
    assert post(harness, payload, headers) == "applied"
    assert captures(harness, UUID(order["order_id"])) == 1
    assert provider_captures(harness) == 1


def test_a_webhook_for_a_cancelled_order_moves_nothing(harness):
    order = harness.opened()
    payload, headers = delivery(harness, order)
    harness.clock.advance(hours=49)
    asyncio.run(harness.service.run_due_work())
    order_id = UUID(order["order_id"])
    assert harness.repo.orders[order_id].state == "CANCELLED"
    assert post(harness, payload, headers) == "applied"
    assert harness.repo.orders[order_id].state == "CANCELLED"
    assert captures(harness, order_id) == 0 and provider_captures(harness) == 0
