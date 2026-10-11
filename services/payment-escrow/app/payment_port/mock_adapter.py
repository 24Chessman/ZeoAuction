"""Deterministic ``MockPaymentAdapter`` (ADR-0007, #59). Test mode only; no money moves.

Deterministic means: the same calls in the same order always give the same results and the
same provider references, with no network, keys or randomness. That is what lets the saga's
1000-run ledger property test (FR-TEST-6) and the demo run offline.

It mimics the Razorpay flow of ADR-0009: ``create_checkout`` opens a ``mock_order_...``,
:meth:`MockPaymentAdapter.simulate_payment` plays the buyer paying in Checkout (an authorized
``mock_pay_...`` plus the handler signature), and webhooks use Razorpay's body shape signed
with ``X-Mock-Signature``.

Failure injection, so every saga branch can be exercised:

* **Amount conventions** (like a provider's test cards): an amount ending in ``.13`` is
  declined (``card_declined``); one ending in ``.99`` fails transiently on its first attempt,
  then succeeds when retried with the same key.
* **Explicit plans**: ``transient_failures={"order:42:capture": 3}`` makes the first three
  attempts with that key fail transiently; ``declines={"order:42:capture"}`` declines it.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.payment_port.port import (
    CheckoutSession,
    IdempotencyMismatch,
    InvalidPaymentRequest,
    PaymentResult,
    PaymentStatus,
    ProviderEvent,
    TransientPaymentError,
)
from app.payment_port.razorpay_adapter import lower_keys, parse_event, to_paise

DECLINE_CENTS = "13"
TRANSIENT_ONCE_CENTS = "99"
MOCK_KEY_ID = "mock_key"
MOCK_SECRET = "mock-checkout-secret"  # noqa: S105 - the mock's fixed test secret
MOCK_WEBHOOK_SECRET = "mock-webhook-secret"  # noqa: S105 - the mock's fixed test secret


@dataclass(frozen=True)
class _Request:
    operation: str
    target: str
    amount: Decimal
    currency: str


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class MockPaymentAdapter:
    provider = "mock"

    def __init__(
        self,
        *,
        transient_failures: dict[str, int] | None = None,
        declines: set[str] | None = None,
        webhook_secret: str = MOCK_WEBHOOK_SECRET,
    ) -> None:
        self._transient = dict(transient_failures or {})
        self._declines = set(declines or ())
        self._webhook_secret = webhook_secret.encode()
        self._results: dict[str, tuple[_Request, PaymentResult]] = {}
        self._attempts: dict[str, int] = {}
        self.orders: dict[str, tuple[Decimal, str]] = {}  # mock_order -> (amount, currency)
        self.authorized: dict[str, tuple[Decimal, str]] = {}  # mock_pay -> (amount, currency)
        self.captured: dict[str, Decimal] = {}  # mock_pay -> amount still refundable
        self.paid_out: dict[str, Decimal] = {}  # payout ref -> amount
        self.calls: list[tuple[str, str]] = []  # (operation, idempotency key), for tests

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def reference(operation: str, idempotency_key: str) -> str:
        return f"mock_{operation}_{_digest(f'{operation}:{idempotency_key}')[:20]}"

    @staticmethod
    def order_ref(order_id: UUID) -> str:
        return f"mock_order_{_digest(str(order_id))[:14]}"

    @staticmethod
    def payment_ref(provider_order_id: str) -> str:
        return f"mock_pay_{_digest(provider_order_id)[:14]}"

    @staticmethod
    def checkout_signature(provider_order_id: str, payment_id: str) -> str:
        return hmac.new(MOCK_SECRET.encode(), f"{provider_order_id}|{payment_id}".encode(),
                        hashlib.sha256).hexdigest()

    def _replay_or_fail(self, key: str, request: _Request) -> PaymentResult | None:
        self.calls.append((request.operation, key))
        if key in self._results:
            original, result = self._results[key]
            if original != request:
                raise IdempotencyMismatch(f"{key} was used for {original.operation} "
                                          f"{original.amount} {original.currency}")
            return result
        attempt = self._attempts.get(key, 0) + 1
        self._attempts[key] = attempt
        planned = self._transient.get(key, 0)
        cents = f"{request.amount:.2f}"[-2:]
        if attempt <= planned or (cents == TRANSIENT_ONCE_CENTS and attempt == 1):
            raise TransientPaymentError(f"mock provider timeout on attempt {attempt} for {key}")
        return None

    def _finish(self, key: str, request: _Request, ref: str | None = None) -> PaymentResult:
        declined = key in self._declines or f"{request.amount:.2f}".endswith("." + DECLINE_CENTS)
        result = PaymentResult(
            status=PaymentStatus.DECLINED if declined else PaymentStatus.SUCCEEDED,
            provider_ref=ref or self.reference(request.operation, key),
            amount=request.amount,
            currency=request.currency,
            idempotency_key=key,
            decline_reason="card_declined" if declined else None,
        )
        self._results[key] = (request, result)
        return result

    @staticmethod
    def _positive(amount: Decimal) -> None:
        if not isinstance(amount, Decimal) or amount <= 0:
            raise InvalidPaymentRequest("amount must be a positive Decimal")

    # ------------------------------------------------------------------ Checkout

    async def create_checkout(
        self, order_id: UUID, amount: Decimal, currency: str, receipt: str
    ) -> CheckoutSession:
        self._positive(amount)
        ref = self.order_ref(order_id)
        self.orders[ref] = (amount, currency)
        return CheckoutSession(provider=self.provider, provider_order_id=ref, amount=amount,
                               currency=currency, key_id=MOCK_KEY_ID)

    def simulate_payment(self, provider_order_id: str) -> tuple[str, str]:
        """The buyer pays in the simulated Checkout: returns ``(payment_id, signature)`` exactly
        as Razorpay's Checkout handler would."""
        payment_id = self.payment_ref(provider_order_id)
        if provider_order_id in self.orders:
            self.authorized[payment_id] = self.orders[provider_order_id]
        return payment_id, self.checkout_signature(provider_order_id, payment_id)

    def verify_checkout(self, provider_order_id: str, payment_id: str, signature: str) -> None:
        expected = self.checkout_signature(provider_order_id, payment_id)
        if not hmac.compare_digest(expected, signature or ""):
            raise InvalidPaymentRequest("Checkout signature does not match")
        if provider_order_id in self.orders:
            self.authorized.setdefault(payment_id, self.orders[provider_order_id])

    # ------------------------------------------------------------------ money

    async def capture(
        self, payment_ref: str, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        self._positive(amount)
        if not payment_ref.startswith("mock_pay_"):
            raise InvalidPaymentRequest(f"unknown payment {payment_ref}")
        # A restarted service has forgotten its authorizations; the deterministic reference
        # is then trusted, as the provider would still have it.
        known = self.authorized.get(payment_ref)
        if known and (amount, currency) != known:
            raise InvalidPaymentRequest("capture must equal the authorized amount")
        request = _Request("capture", payment_ref, amount, currency)
        replay = self._replay_or_fail(idempotency_key, request)
        if replay:
            return replay
        result = self._finish(idempotency_key, request, ref=payment_ref)
        if result.succeeded:
            self.captured[payment_ref] = amount
        return result

    async def refund(
        self, capture_ref: str, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        self._positive(amount)
        if capture_ref not in self.captured:
            raise InvalidPaymentRequest(f"unknown capture {capture_ref}")
        request = _Request("refund", capture_ref, amount, currency)
        replay = self._replay_or_fail(idempotency_key, request)
        if replay:
            return replay
        if amount > self.captured[capture_ref]:
            raise InvalidPaymentRequest("refund exceeds the refundable amount")
        result = self._finish(idempotency_key, request)
        if result.succeeded:
            self.captured[capture_ref] -= amount
        return result

    async def payout(
        self, capture_ref: str, seller_id: UUID, amount: Decimal, currency: str,
        idempotency_key: str,
    ) -> PaymentResult:
        self._positive(amount)
        if capture_ref not in self.captured:
            raise InvalidPaymentRequest(f"unknown capture {capture_ref}")
        request = _Request("payout", f"{capture_ref}:{seller_id}", amount, currency)
        replay = self._replay_or_fail(idempotency_key, request)
        if replay:
            return replay
        result = self._finish(idempotency_key, request)
        if result.succeeded:
            self.paid_out[result.provider_ref] = amount
        return result

    # ------------------------------------------------------------------ webhooks

    def sign(self, payload: bytes) -> str:
        """What the mock provider sends in ``X-Mock-Signature`` (for tests and demos)."""
        return hmac.new(self._webhook_secret, payload, hashlib.sha256).hexdigest()

    def webhook(self, event_type: str, provider_order_id: str, payment_id: str,
                amount: Decimal, currency: str, event_id: str) -> tuple[bytes, dict[str, str]]:
        """A signed delivery in Razorpay's body shape, as the mock provider would send it."""
        body = {"entity": "event", "event": event_type, "contains": ["payment"], "payload": {
            "payment": {"entity": {"id": payment_id, "order_id": provider_order_id,
                                   "amount": to_paise(amount), "currency": currency}}}}
        payload = json.dumps(body).encode()
        return payload, {"X-Mock-Signature": self.sign(payload), "X-Mock-Event-Id": event_id}

    def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        lowered = lower_keys(headers)
        if not hmac.compare_digest(self.sign(payload), lowered.get("x-mock-signature", "")):
            raise InvalidPaymentRequest("webhook signature does not match")
        try:
            body = json.loads(payload)
        except ValueError as exc:
            raise InvalidPaymentRequest("webhook body is not JSON") from exc
        event_id = lowered.get("x-mock-event-id") or _digest(payload.decode(errors="replace"))
        return parse_event(self.provider, event_id, body)
