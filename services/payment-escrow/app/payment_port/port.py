"""``PaymentPort``: the only way the platform talks to a payment provider (ADR-0007, #59).

The settlement saga (Plan 5) codes against this interface; the provider chosen in ADR-0009 is
one adapter behind it, and :class:`~app.payment_port.mock_adapter.MockPaymentAdapter` is the
deterministic default locally and in CI (``PAYMENT_ADAPTER=mock``).

The model is manual capture, the escrow primitive: ``authorize`` reserves the buyer's funds,
``capture`` moves them into platform custody, ``payout`` releases the seller's share and
``refund`` returns money to the buyer. Every call carries an idempotency key derived from the
order and the operation (``order:{id}:capture``, SDD 5.2.3): repeating a call with the same key
returns the original result and moves no money twice.
"""

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
    """Timeout or provider outage: retry later with the **same** idempotency key."""


class IdempotencyMismatch(PaymentError):
    """The key was already used for a different operation or amount; this is a bug."""


class InvalidPaymentRequest(PaymentError):
    """The request can never succeed (unknown reference, refund above capture, ...)."""


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
class ProviderEvent:
    """A verified provider webhook (FR-PAY-7); de-duplicated on ``(provider, event_id)``."""

    provider: str
    event_id: str
    event_type: str
    provider_ref: str


class PaymentPort(Protocol):
    provider: str

    async def authorize(
        self, order_id: UUID, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        """Reserve the buyer's funds without moving them (manual capture)."""
        ...

    async def capture(
        self, authorization_ref: str, amount: Decimal, idempotency_key: str
    ) -> PaymentResult:
        """Move an authorized amount into platform custody (saga step S2)."""
        ...

    async def refund(
        self, capture_ref: str, amount: Decimal, idempotency_key: str
    ) -> PaymentResult:
        """Return up to the captured amount to the buyer."""
        ...

    async def payout(
        self, seller_id: UUID, amount: Decimal, currency: str, idempotency_key: str
    ) -> PaymentResult:
        """Release the seller's net share (captured total minus the fee)."""
        ...

    def verify_webhook(self, payload: bytes, signature: str) -> ProviderEvent:
        """Check the provider's signature and parse the event; raise on a bad signature."""
        ...
