"""``PaymentPort``: the only way the platform talks to a payment provider (ADR-0007, #59).

The settlement saga codes against this interface. ADR-0009 chose **Razorpay test mode**
(:mod:`app.payment_port.razorpay_adapter`); the deterministic
:class:`~app.payment_port.mock_adapter.MockPaymentAdapter` is the default locally and in CI
(``PAYMENT_ADAPTER=mock``).

The model is manual capture, the escrow primitive, with the buyer in the loop:

1. ``create_checkout`` opens a provider order for the invoice total. The winner pays it in the
   provider's Checkout, which **authorises** the payment without capturing it.
2. The authorisation reaches us twice, and either is enough: the browser hands back a signed
   payment id (``verify_checkout``), and the provider sends a signed webhook
   (``verify_webhook``, event ``payment.authorized``).
3. ``capture`` moves the authorised amount into platform custody (saga step S2).
4. ``payout`` releases the seller's net share, and ``refund`` returns money to the buyer.

Every money-moving call carries an idempotency key derived from the order and the operation
(``order:{id}:capture``, SDD 5.2.3): repeating a call with the same key returns the original
result and moves no money twice.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class PaymentStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    DECLINED = "DECLINED"  # definitive: retrying with the same key will not help


class PaymentError(Exception):
    """Base class for provider-side failures."""


class TransientPaymentError(PaymentError):
    """Timeout, rate limit or provider outage: retry later with the **same** idempotency key."""


class IdempotencyMismatch(PaymentError):
    """The key was already used for a different operation or amount; this is a bug."""


class InvalidPaymentRequest(PaymentError):
    """The request can never succeed (bad signature, unknown reference, refund above capture)."""


@dataclass(frozen=True)
class PaymentResult:
    status: PaymentStatus
    provider_ref: str
    amount: Decimal
    currency: str
    idempotency_key: str
    decline_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is PaymentStatus.SUCCEEDED


@dataclass(frozen=True)
class CheckoutSession:
    """What the browser needs to open the provider's Checkout for one order."""

    provider: str
    provider_order_id: str
    amount: Decimal
    currency: str
    # Public key the Checkout script is opened with (Razorpay key_id); never the secret.
    key_id: str | None = None


@dataclass(frozen=True)
class ProviderEvent:
    """A verified provider webhook (FR-PAY-7); de-duplicated on ``(provider, event_id)``."""

    provider: str
    event_id: str
    event_type: str
    provider_ref: str | None = None  # the payment (pay_...) the event is about
    provider_order_id: str | None = None
    amount: Decimal | None = None
    currency: str | None = None


class PaymentPort(Protocol):
    provider: str

    async def create_checkout(
        self, order_id: UUID, amount: Decimal, currency: str, receipt: str
    ) -> CheckoutSession:
        """Open a provider order for ``amount`` that the buyer pays with manual capture."""
        ...

    def verify_checkout(self, provider_order_id: str, payment_id: str, signature: str) -> None:
        """Check the signature Checkout hands the browser; raise InvalidPaymentRequest if wrong."""
        ...

    async def capture(
        self, payment_ref: str, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        """Move an authorised payment into platform custody (saga step S2)."""
        ...

    async def refund(
        self, capture_ref: str, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        """Return up to the captured amount to the buyer."""
        ...

    async def payout(
        self, capture_ref: str, seller_id: UUID, amount: Decimal, currency: str,
        idempotency_key: str,
    ) -> PaymentResult:
        """Release the seller's net share (captured total minus the fee) of a captured payment."""
        ...

    def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> ProviderEvent:
        """Check the provider's signature header and parse the event; raise on a bad signature."""
        ...
