"""Razorpay adapter for :class:`~app.payment_port.port.PaymentPort` (#60, ADR-0009).

**Test mode only.** The adapter refuses any key that is not a ``rzp_test_`` key, so no real
money can move from this codebase (NFR-SEC-4). Keys come from the environment (Render
environment groups when hosted), never from the repository.

How the port maps onto Razorpay's REST API (``https://api.razorpay.com/v1``, HTTP basic auth
with ``key_id:key_secret``; amounts are integers in paise):

* ``create_checkout`` -> ``POST /orders`` with ``payment_capture: 0``, so a payment made in
  Checkout stays **authorized** until we capture it (manual capture, the escrow primitive).
* ``verify_checkout`` -> Checkout's handler signature,
  ``HMAC-SHA256(key_secret, "{order_id}|{payment_id}")``.
* ``capture`` -> ``POST /payments/{id}/capture``. Razorpay has no idempotency key for capture,
  so a refused capture is resolved by reading the payment back: already ``captured`` for the
  same amount is the original success (a retry after a lost response), ``failed`` is a decline.
* ``refund`` -> ``POST /payments/{id}/refund``; ``payout`` -> a Route transfer,
  ``POST /payments/{id}/transfers``, to the seller's linked account. Both write our idempotency
  key into ``notes`` and look for it first, so a retry never refunds or pays out twice.
* ``verify_webhook`` -> ``X-Razorpay-Signature`` = ``HMAC-SHA256(webhook_secret, raw body)``;
  ``X-Razorpay-Event-Id`` de-duplicates deliveries.

Timeouts, 429 and 5xx raise :class:`TransientPaymentError` (retry with the same key, and they
count towards the Orchestration -> Payment breaker); other 4xx are definitive.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from app.payment_port.port import (
    CheckoutSession,
    IdempotencyMismatch,
    InvalidPaymentRequest,
    PaymentResult,
    PaymentStatus,
    ProviderEvent,
    TransientPaymentError,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.razorpay.com/v1"
TEST_KEY_PREFIX = "rzp_test_"
RECEIPT_MAX = 40  # Razorpay's limit on order and refund receipts
_CENT = Decimal("0.01")


def to_paise(amount: Decimal) -> int:
    if not isinstance(amount, Decimal) or amount <= 0:
        raise InvalidPaymentRequest("amount must be a positive Decimal")
    if amount != amount.quantize(_CENT):
        raise InvalidPaymentRequest(f"amount {amount} has more than two decimals")
    return int(amount * 100)


def from_paise(paise: int) -> Decimal:
    return (Decimal(int(paise)) / 100).quantize(_CENT)


def signature(secret: str, message: str | bytes) -> str:
    data = message.encode() if isinstance(message, str) else message
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


def lower_keys(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def parse_event(provider: str, event_id: str, body: Any) -> ProviderEvent:
    """Read a Razorpay-shaped webhook body (the mock sends the same shape)."""
    if not isinstance(body, dict) or not isinstance(body.get("event"), str):
        raise InvalidPaymentRequest("webhook body has no event")
    entity = (body.get("payload") or {}).get("payment", {}).get("entity") or {}
    amount = entity.get("amount")
    return ProviderEvent(
        provider=provider,
        event_id=event_id,
        event_type=body["event"],
        provider_ref=entity.get("id"),
        provider_order_id=entity.get("order_id"),
        amount=from_paise(amount) if isinstance(amount, int) else None,
        currency=entity.get("currency"),
    )


def _error(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return f"HTTP {response.status_code}"
    return f"{error.get('code', response.status_code)}: {error.get('description', '')}".strip()


class RazorpayAdapter:
    provider = "razorpay"

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        webhook_secret: str,
        linked_account_for: Callable[[UUID], str | None] = lambda _seller: None,
        http: httpx.AsyncClient | None = None,
        api_url: str = API_URL,
    ) -> None:
        if not key_id.startswith(TEST_KEY_PREFIX):
            raise ValueError("Razorpay is test mode only: RAZORPAY_KEY_ID must be a rzp_test_ key")
        if not key_secret or not webhook_secret:
            raise ValueError("RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET are required")
        self.key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self._linked_account_for = linked_account_for
        self.http = http or httpx.AsyncClient(base_url=api_url, auth=(key_id, key_secret),
                                              timeout=httpx.Timeout(10.0))

    async def aclose(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------------ transport

    async def _call(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        try:
            response = await self.http.request(method, path, json=body)
        except httpx.TransportError as exc:  # timeouts, refused connections, resets
            raise TransientPaymentError(f"Razorpay {method} {path}: {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientPaymentError(f"Razorpay {method} {path}: {_error(response)}")
        return response

    async def _ok(self, method: str, path: str, body: dict | None = None) -> dict:
        response = await self._call(method, path, body)
        if response.status_code >= 400:
            raise InvalidPaymentRequest(f"Razorpay {method} {path}: {_error(response)}")
        return response.json()

    async def _fetch_payment(self, payment_id: str) -> dict:
        return await self._ok("GET", f"/payments/{payment_id}")

    @staticmethod
    def _find_by_key(collection: dict, key: str) -> dict | None:
        for item in collection.get("items", []):
            if (item.get("notes") or {}).get("idempotency_key") == key:
                return item
        return None

    @staticmethod
    def _result(ref: str, amount: Decimal, currency: str, key: str) -> PaymentResult:
        return PaymentResult(status=PaymentStatus.SUCCEEDED, provider_ref=ref, amount=amount,
                             currency=currency, idempotency_key=key)

    # ------------------------------------------------------------------ PaymentPort

    async def create_checkout(
        self, order_id: UUID, amount: Decimal, currency: str, receipt: str
    ) -> CheckoutSession:
        body = {
            "amount": to_paise(amount),
            "currency": currency,
            "receipt": receipt[:RECEIPT_MAX],
            "payment_capture": 0,  # manual capture: payments stay authorized until we capture
            "notes": {"order_id": str(order_id), "mode": "test"},
        }
        created = await self._ok("POST", "/orders", body)
        if created.get("amount") != body["amount"] or created.get("currency") != currency:
            raise InvalidPaymentRequest("Razorpay created an order for a different amount")
        return CheckoutSession(provider=self.provider, provider_order_id=created["id"],
                               amount=amount, currency=currency, key_id=self.key_id)

    def verify_checkout(self, provider_order_id: str, payment_id: str, signature_: str) -> None:
        expected = signature(self._key_secret, f"{provider_order_id}|{payment_id}")
        if not hmac.compare_digest(expected, signature_ or ""):
            raise InvalidPaymentRequest("Checkout signature does not match")

    async def capture(
        self, payment_ref: str, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        paise = to_paise(amount)
        response = await self._call("POST", f"/payments/{payment_ref}/capture",
                                    {"amount": paise, "currency": currency})
        if response.status_code < 400:
            captured = response.json()
            if captured.get("status") != "captured" or captured.get("amount") != paise:
                raise InvalidPaymentRequest(f"capture of {payment_ref} returned "
                                            f"{captured.get('status')}")
            return self._result(payment_ref, amount, currency, idempotency_key)
        # Refused: find out why from the payment itself.
        payment = await self._fetch_payment(payment_ref)
        status = payment.get("status")
        if status == "captured" and payment.get("amount") == paise:
            logger.info("Payment %s was already captured; treating as the original success",
                        payment_ref)
            return self._result(payment_ref, amount, currency, idempotency_key)
        if status == "failed":
            return PaymentResult(
                status=PaymentStatus.DECLINED, provider_ref=payment_ref, amount=amount,
                currency=currency, idempotency_key=idempotency_key,
                decline_reason=payment.get("error_reason") or payment.get("error_code")
                or "payment_failed",
            )
        raise InvalidPaymentRequest(f"capture of {payment_ref} refused: {_error(response)}")

    async def refund(
        self, capture_ref: str, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        paise = to_paise(amount)
        existing = self._find_by_key(
            await self._ok("GET", f"/payments/{capture_ref}/refunds"), idempotency_key)
        if existing is None:
            existing = await self._ok("POST", f"/payments/{capture_ref}/refund", {
                "amount": paise,
                "speed": "normal",
                "receipt": idempotency_key[-RECEIPT_MAX:],
                "notes": {"idempotency_key": idempotency_key},
            })
        elif existing.get("amount") != paise:
            raise IdempotencyMismatch(f"{idempotency_key} already refunded a different amount")
        return self._result(existing["id"], amount, currency, idempotency_key)

    async def payout(
        self, capture_ref: str, seller_id: UUID, amount: Decimal, currency: str,
        idempotency_key: str,
    ) -> PaymentResult:
        paise = to_paise(amount)
        account = self._linked_account_for(seller_id)
        if not account:
            raise InvalidPaymentRequest(f"seller {seller_id} has no Razorpay linked account")
        existing = self._find_by_key(
            await self._ok("GET", f"/payments/{capture_ref}/transfers"), idempotency_key)
        if existing is None:
            created = await self._ok("POST", f"/payments/{capture_ref}/transfers", {
                "transfers": [{
                    "account": account,
                    "amount": paise,
                    "currency": currency,
                    "on_hold": False,
                    "notes": {"idempotency_key": idempotency_key, "seller_id": str(seller_id)},
                }],
            })
            items = created.get("items") or []
            if not items:
                raise InvalidPaymentRequest("Razorpay returned no transfer")
            existing = items[0]
        elif existing.get("amount") != paise:
            raise IdempotencyMismatch(f"{idempotency_key} already paid out a different amount")
        return self._result(existing["id"], amount, currency, idempotency_key)

    def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        lowered = lower_keys(headers)
        expected = signature(self._webhook_secret, payload)
        if not hmac.compare_digest(expected, lowered.get("x-razorpay-signature", "")):
            raise InvalidPaymentRequest("webhook signature does not match")
        try:
            body = json.loads(payload)
        except ValueError as exc:
            raise InvalidPaymentRequest("webhook body is not JSON") from exc
        event_id = lowered.get("x-razorpay-event-id") or hashlib.sha256(payload).hexdigest()
        return parse_event(self.provider, event_id, body)
