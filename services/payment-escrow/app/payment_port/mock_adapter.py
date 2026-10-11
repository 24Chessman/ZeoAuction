"""Deterministic ``MockPaymentAdapter`` (ADR-0007, #59). Test mode only; no money moves.

Deterministic means: the same calls in the same order always give the same results and the
same provider references, with no network, keys or randomness. That is what lets the saga's
1000-run ledger property test (FR-TEST-6) and the demo run offline.

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
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.payment_port.port import (
    IdempotencyMismatch,
    InvalidPaymentRequest,
    PaymentResult,
    PaymentStatus,
    ProviderEvent,
    TransientPaymentError,
)

DECLINE_CENTS = "13"
TRANSIENT_ONCE_CENTS = "99"
MOCK_WEBHOOK_SECRET = "mock-webhook-secret"  # noqa: S105 - the mock's fixed test secret


@dataclass(frozen=True)
class _Request:
    operation: str
    target: str
    amount: Decimal
    currency: str


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
        self.authorized: dict[str, Decimal] = {}  # authorization ref -> amount
        self.captured: dict[str, Decimal] = {}  # capture ref -> amount still refundable
        self.paid_out: dict[str, Decimal] = {}  # payout ref -> amount
        self.calls: list[tuple[str, str]] = []  # (operation, idempotency key), for tests

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def reference(operation: str, idempotency_key: str) -> str:
        digest = hashlib.sha256(f"{operation}:{idempotency_key}".encode()).hexdigest()
        return f"mock_{operation}_{digest[:20]}"

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

    def _finish(self, key: str, request: _Request, *, declined: bool = False,
                reason: str | None = None) -> PaymentResult:
        declined = declined or key in self._declines or f"{request.amount:.2f}".endswith(
            "." + DECLINE_CENTS)
        result = PaymentResult(
            status=PaymentStatus.DECLINED if declined else PaymentStatus.SUCCEEDED,
            provider_ref=self.reference(request.operation, key),
            amount=request.amount,
            currency=request.currency,
            idempotency_key=key,
            decline_reason=(reason or "card_declined") if declined else None,
        )
        self._results[key] = (request, result)
        return result

    @staticmethod
    def _positive(amount: Decimal) -> None:
        if not isinstance(amount, Decimal) or amount <= 0:
            raise InvalidPaymentRequest("amount must be a positive Decimal")

    # ------------------------------------------------------------------ PaymentPort

    async def authorize(
        self, order_id: UUID, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        self._positive(amount)
        request = _Request("authorize", str(order_id), amount, currency)
        replay = self._replay_or_fail(idempotency_key, request)
        if replay:
            return replay
        result = self._finish(idempotency_key, request)
        if result.succeeded:
            self.authorized[result.provider_ref] = amount
        return result

    async def capture(
        self, authorization_ref: str, amount: Decimal, idempotency_key: str
    ) -> PaymentResult:
        self._positive(amount)
        if authorization_ref not in self.authorized:
            raise InvalidPaymentRequest(f"unknown authorization {authorization_ref}")
        if amount > self.authorized[authorization_ref]:
            raise InvalidPaymentRequest("capture exceeds the authorized amount")
        currency = self._currency_of(authorization_ref)
        request = _Request("capture", authorization_ref, amount, currency)
        replay = self._replay_or_fail(idempotency_key, request)
        if replay:
            return replay
        result = self._finish(idempotency_key, request)
        if result.succeeded:
            self.captured[result.provider_ref] = amount
        return result

    async def refund(
        self, capture_ref: str, amount: Decimal, idempotency_key: str
    ) -> PaymentResult:
        self._positive(amount)
        if capture_ref not in self.captured:
            raise InvalidPaymentRequest(f"unknown capture {capture_ref}")
        request = _Request("refund", capture_ref, amount, self._currency_of(capture_ref))
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
        self, seller_id: UUID, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        self._positive(amount)
        request = _Request("payout", str(seller_id), amount, currency)
        replay = self._replay_or_fail(idempotency_key, request)
        if replay:
            return replay
        result = self._finish(idempotency_key, request)
        if result.succeeded:
            self.paid_out[result.provider_ref] = amount
        return result

    def _currency_of(self, ref: str) -> str:
        for request, result in self._results.values():
            if result.provider_ref == ref:
                return request.currency
        raise InvalidPaymentRequest(f"unknown reference {ref}")

    # ------------------------------------------------------------------ webhooks

    def sign(self, payload: bytes) -> str:
        """What the mock provider would send in its signature header (for tests and demos)."""
        return hmac.new(self._webhook_secret, payload, hashlib.sha256).hexdigest()

    def verify_webhook(self, payload: bytes, signature: str) -> ProviderEvent:
        if not hmac.compare_digest(self.sign(payload), signature):
            raise InvalidPaymentRequest("webhook signature does not match")
        body = json.loads(payload)
        return ProviderEvent(provider=self.provider, event_id=body["id"],
                             event_type=body["type"], provider_ref=body["ref"])
