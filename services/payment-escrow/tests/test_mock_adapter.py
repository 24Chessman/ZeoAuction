import json
from decimal import Decimal
from uuid import UUID

import pytest

from app.payment_port.mock_adapter import MockPaymentAdapter
from app.payment_port.port import (
    IdempotencyMismatch,
    InvalidPaymentRequest,
    PaymentPort,
    PaymentStatus,
    TransientPaymentError,
)

ORDER = UUID("00000000-0000-4000-8000-000000000301")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
TOTAL = Decimal("1275.00")  # winning bid 1250.00 + fee 25.00


async def settle(adapter: MockPaymentAdapter, total: Decimal = TOTAL):
    auth = await adapter.authorize(ORDER, total, "USD", f"order:{ORDER}:authorize")
    capture = await adapter.capture(auth.provider_ref, total, f"order:{ORDER}:capture")
    return auth, capture


def test_the_mock_satisfies_the_port():
    adapter: PaymentPort = MockPaymentAdapter()
    assert adapter.provider == "mock"


async def test_happy_path_authorize_capture_payout():
    adapter = MockPaymentAdapter()
    auth, capture = await settle(adapter)
    assert auth.succeeded and capture.succeeded
    payout = await adapter.payout(SELLER, Decimal("1250.00"), "USD", f"order:{ORDER}:release")
    assert payout.status is PaymentStatus.SUCCEEDED
    assert payout.amount == Decimal("1250.00")


async def test_results_and_references_are_deterministic():
    first, second = MockPaymentAdapter(), MockPaymentAdapter()
    assert [r.provider_ref for r in await settle(first)] == [
        r.provider_ref for r in await settle(second)]


async def test_same_key_returns_the_original_result_and_moves_money_once():
    adapter = MockPaymentAdapter()
    _, capture = await settle(adapter)
    for _ in range(3):
        again = await adapter.payout(SELLER, Decimal("1250.00"), "USD", "order:1:release")
    assert again == await adapter.payout(SELLER, Decimal("1250.00"), "USD", "order:1:release")
    assert len(adapter.paid_out) == 1


async def test_reusing_a_key_for_a_different_amount_is_a_bug():
    adapter = MockPaymentAdapter()
    await adapter.payout(SELLER, Decimal("10.00"), "USD", "order:1:release")
    with pytest.raises(IdempotencyMismatch):
        await adapter.payout(SELLER, Decimal("11.00"), "USD", "order:1:release")


async def test_amount_ending_in_13_is_declined_definitively():
    adapter = MockPaymentAdapter()
    result = await adapter.authorize(ORDER, Decimal("100.13"), "USD", "k-decline")
    assert result.status is PaymentStatus.DECLINED
    assert result.decline_reason == "card_declined"
    assert (await adapter.authorize(ORDER, Decimal("100.13"), "USD", "k-decline")) == result
    assert adapter.authorized == {}


async def test_amount_ending_in_99_fails_once_then_succeeds_on_retry():
    adapter = MockPaymentAdapter()
    with pytest.raises(TransientPaymentError):
        await adapter.authorize(ORDER, Decimal("100.99"), "USD", "k-flaky")
    assert (await adapter.authorize(ORDER, Decimal("100.99"), "USD", "k-flaky")).succeeded


async def test_planned_transient_failures_then_success():
    key = f"order:{ORDER}:capture"
    adapter = MockPaymentAdapter(transient_failures={key: 2})
    auth = await adapter.authorize(ORDER, TOTAL, "USD", "auth-1")
    for _ in range(2):
        with pytest.raises(TransientPaymentError):
            await adapter.capture(auth.provider_ref, TOTAL, key)
    assert (await adapter.capture(auth.provider_ref, TOTAL, key)).succeeded
    assert adapter.calls.count(("capture", key)) == 3


async def test_planned_decline():
    adapter = MockPaymentAdapter(declines={"auth-x"})
    assert (await adapter.authorize(ORDER, TOTAL, "USD", "auth-x")).status is (
        PaymentStatus.DECLINED)


async def test_capture_needs_a_live_authorization_within_its_amount():
    adapter = MockPaymentAdapter()
    with pytest.raises(InvalidPaymentRequest):
        await adapter.capture("mock_authorize_missing", TOTAL, "c-1")
    auth = await adapter.authorize(ORDER, TOTAL, "USD", "a-1")
    with pytest.raises(InvalidPaymentRequest):
        await adapter.capture(auth.provider_ref, TOTAL + Decimal("0.01"), "c-2")


async def test_refunds_never_exceed_the_capture():
    adapter = MockPaymentAdapter()
    _, capture = await settle(adapter)
    partial = await adapter.refund(capture.provider_ref, Decimal("1250.00"), "order:1:refund")
    assert partial.succeeded and partial.currency == "USD"
    with pytest.raises(InvalidPaymentRequest):
        await adapter.refund(capture.provider_ref, Decimal("25.01"), "order:1:refund-2")
    assert (await adapter.refund(capture.provider_ref, Decimal("25.00"), "order:1:fee")).succeeded
    with pytest.raises(InvalidPaymentRequest):
        await adapter.refund("mock_capture_unknown", Decimal("1.00"), "r-x")


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1.00"), 10.0])
async def test_amounts_must_be_positive_decimals(amount):
    with pytest.raises(InvalidPaymentRequest):
        await MockPaymentAdapter().payout(SELLER, amount, "USD", "p-1")


def test_webhooks_are_verified_by_signature():
    adapter = MockPaymentAdapter()
    payload = json.dumps({"id": "evt_1", "type": "payment.captured", "ref": "mock_capture_1"})
    event = adapter.verify_webhook(payload.encode(), adapter.sign(payload.encode()))
    assert (event.provider, event.event_id, event.event_type) == (
        "mock", "evt_1", "payment.captured")
    with pytest.raises(InvalidPaymentRequest):
        adapter.verify_webhook(payload.encode(), "0" * 64)
