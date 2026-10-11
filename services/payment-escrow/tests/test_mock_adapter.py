from decimal import Decimal
from uuid import UUID

import pytest

from app.payment_port.mock_adapter import MOCK_KEY_ID, MockPaymentAdapter
from app.payment_port.port import (
    IdempotencyMismatch,
    InvalidPaymentRequest,
    PaymentPort,
    PaymentStatus,
    TransientPaymentError,
)

ORDER = UUID("00000000-0000-4000-8000-000000000301")
SELLER = UUID("00000000-0000-4000-8000-000000000002")
TOTAL = Decimal("1349.00")  # winning bid 1250.00 + fee 99.00
CAPTURE_KEY = f"order:{ORDER}:capture"


async def paid(adapter: MockPaymentAdapter, total: Decimal = TOTAL) -> str:
    session = await adapter.create_checkout(ORDER, total, "INR", "ZA-202610-1")
    payment_id, signature = adapter.simulate_payment(session.provider_order_id)
    adapter.verify_checkout(session.provider_order_id, payment_id, signature)
    return payment_id


async def captured(adapter: MockPaymentAdapter, total: Decimal = TOTAL) -> str:
    payment_id = await paid(adapter, total)
    result = await adapter.capture(payment_id, total, "INR", CAPTURE_KEY)
    assert result.succeeded
    return result.provider_ref


def test_the_mock_satisfies_the_port():
    adapter: PaymentPort = MockPaymentAdapter()
    assert adapter.provider == "mock"


async def test_checkout_is_deterministic_and_signed():
    first, second = MockPaymentAdapter(), MockPaymentAdapter()
    a = await first.create_checkout(ORDER, TOTAL, "INR", "r")
    b = await second.create_checkout(ORDER, TOTAL, "INR", "r")
    assert a == b and a.key_id == MOCK_KEY_ID and a.provider_order_id.startswith("mock_order_")
    assert first.simulate_payment(a.provider_order_id) == second.simulate_payment(
        b.provider_order_id)
    with pytest.raises(InvalidPaymentRequest):
        first.verify_checkout(a.provider_order_id, "mock_pay_other", "0" * 64)


async def test_happy_path_capture_payout_refund():
    adapter = MockPaymentAdapter()
    ref = await captured(adapter)
    payout = await adapter.payout(ref, SELLER, Decimal("1250.00"), "INR", f"order:{ORDER}:release")
    assert payout.status is PaymentStatus.SUCCEEDED and payout.amount == Decimal("1250.00")
    refund = await adapter.refund(ref, Decimal("99.00"), "INR", f"order:{ORDER}:refund")
    assert refund.succeeded and adapter.captured[ref] == Decimal("1250.00")


async def test_capture_reference_is_the_payment():
    adapter = MockPaymentAdapter()
    payment_id = await paid(adapter)
    result = await adapter.capture(payment_id, TOTAL, "INR", CAPTURE_KEY)
    assert result.provider_ref == payment_id


async def test_same_key_returns_the_original_result_and_moves_money_once():
    adapter = MockPaymentAdapter()
    payment_id = await paid(adapter)
    results = [await adapter.capture(payment_id, TOTAL, "INR", CAPTURE_KEY) for _ in range(3)]
    assert results[0] == results[1] == results[2]
    assert len(adapter.captured) == 1


async def test_reusing_a_key_for_a_different_amount_is_a_bug():
    adapter = MockPaymentAdapter()
    ref = await captured(adapter)
    await adapter.payout(ref, SELLER, Decimal("10.00"), "INR", "order:1:release")
    with pytest.raises(IdempotencyMismatch):
        await adapter.payout(ref, SELLER, Decimal("11.00"), "INR", "order:1:release")


async def test_amount_ending_in_13_is_declined_definitively():
    adapter = MockPaymentAdapter()
    total = Decimal("1349.13")
    payment_id = await paid(adapter, total)
    result = await adapter.capture(payment_id, total, "INR", "k-decline")
    assert result.status is PaymentStatus.DECLINED and result.decline_reason == "card_declined"
    assert (await adapter.capture(payment_id, total, "INR", "k-decline")) == result
    assert adapter.captured == {}


async def test_amount_ending_in_99_fails_once_then_succeeds_on_retry():
    adapter = MockPaymentAdapter()
    total = Decimal("1349.99")
    payment_id = await paid(adapter, total)
    with pytest.raises(TransientPaymentError):
        await adapter.capture(payment_id, total, "INR", "k-flaky")
    assert (await adapter.capture(payment_id, total, "INR", "k-flaky")).succeeded


async def test_planned_transient_failures_then_success():
    adapter = MockPaymentAdapter(transient_failures={CAPTURE_KEY: 2})
    payment_id = await paid(adapter)
    for _ in range(2):
        with pytest.raises(TransientPaymentError):
            await adapter.capture(payment_id, TOTAL, "INR", CAPTURE_KEY)
    assert (await adapter.capture(payment_id, TOTAL, "INR", CAPTURE_KEY)).succeeded
    assert adapter.calls.count(("capture", CAPTURE_KEY)) == 3


async def test_planned_decline():
    adapter = MockPaymentAdapter(declines={CAPTURE_KEY})
    payment_id = await paid(adapter)
    result = await adapter.capture(payment_id, TOTAL, "INR", CAPTURE_KEY)
    assert result.status is PaymentStatus.DECLINED


async def test_capture_needs_a_mock_payment_for_the_authorized_amount():
    adapter = MockPaymentAdapter()
    with pytest.raises(InvalidPaymentRequest):
        await adapter.capture("pay_real_looking", TOTAL, "INR", "c-1")
    payment_id = await paid(adapter)
    with pytest.raises(InvalidPaymentRequest):
        await adapter.capture(payment_id, TOTAL + Decimal("0.01"), "INR", "c-2")


async def test_a_restarted_mock_trusts_its_deterministic_payment_reference():
    payment_id = await paid(MockPaymentAdapter())
    assert (await MockPaymentAdapter().capture(payment_id, TOTAL, "INR", CAPTURE_KEY)).succeeded


async def test_refunds_and_payouts_never_exceed_the_capture():
    adapter = MockPaymentAdapter()
    ref = await captured(adapter)
    assert (await adapter.refund(ref, Decimal("1250.00"), "INR", "order:1:refund")).succeeded
    with pytest.raises(InvalidPaymentRequest):
        await adapter.refund(ref, Decimal("99.01"), "INR", "order:1:refund-2")
    with pytest.raises(InvalidPaymentRequest):
        await adapter.refund("mock_pay_unknown", Decimal("1.00"), "INR", "r-x")
    with pytest.raises(InvalidPaymentRequest):
        await adapter.payout("mock_pay_unknown", SELLER, Decimal("1.00"), "INR", "p-x")


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1.00"), 10.0])
async def test_amounts_must_be_positive_decimals(amount):
    with pytest.raises(InvalidPaymentRequest):
        await MockPaymentAdapter().create_checkout(ORDER, amount, "INR", "r")


def test_webhooks_are_verified_by_signature():
    adapter = MockPaymentAdapter()
    payload, headers = adapter.webhook("payment.authorized", "mock_order_1", "mock_pay_1",
                                       TOTAL, "INR", "evt_1")
    event = adapter.verify_webhook(payload, headers)
    assert (event.provider, event.event_id, event.event_type, event.provider_ref,
            event.provider_order_id, event.amount, event.currency) == (
        "mock", "evt_1", "payment.authorized", "mock_pay_1", "mock_order_1", TOTAL, "INR")
    with pytest.raises(InvalidPaymentRequest):
        adapter.verify_webhook(payload, {"X-Mock-Signature": "0" * 64})
    with pytest.raises(InvalidPaymentRequest):
        adapter.verify_webhook(b"not json", {"X-Mock-Signature": adapter.sign(b"not json")})
    unnamed = adapter.verify_webhook(payload, {"x-mock-signature": headers["X-Mock-Signature"]})
    assert len(unnamed.event_id) == 64  # derived from the body when the header is absent
