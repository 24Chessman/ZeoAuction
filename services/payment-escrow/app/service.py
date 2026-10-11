"""Payment & Escrow use cases: the fee quote and the settlement forward path (S1-S4).

    S1  open_order       Auction Orchestration reports a CLOSED auction with a winner: order +
                         invoice (winning bid + flat fee, active fee_version)       -> INVOICED
    --  start_checkout   the winner opens Razorpay Checkout for the invoice total
    --  confirm_payment  Checkout's signed handler (or the payment.authorized
        / webhooks       webhook) proves the payment is authorised                  -> AUTHORIZED
    S2  capture          manual capture through PaymentPort, key order:{id}:capture  -> CAPTURED
    S3  hold             HOLD and FEE_RETAIN rows                                    -> IN_ESCROW
    S4  (orchestrator)   HELD on payment.events moves the auction to SETTLED (A7)

A capture that fails transiently, or while the Orchestration -> Payment breaker is open
(3 failures in 30 s, SDD Table 2.2), parks the order in AWAITING_CAPTURE_RETRY, and
:meth:`PaymentService.run_due_work` captures again with the **same** key: settlement is
deferred, never abandoned. A definitive failure, or a winner who never pays within the payment
window, compensates S1 (O4): CANCELLED, invoice voided, no partial settlement remains.

Every step is committed with its ledger rows in one transaction, then published as
``SettlementStep v1``. If the broker is down the step stands, and the failure is counted.
"""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from prometheus_client import CollectorRegistry, Counter

from app.adapters.kafka_producer import SettlementEventPublisher, build_settlement_step
from app.adapters.repository import PaymentRepository, StaleOrder
from app.domain import orders as machine
from app.domain.fees import FeeError, FeeQuote, quote
from app.domain.invoice import Invoice, issue_invoice
from app.domain.ledger import LedgerEntry, capture_entry, hold_entries
from app.domain.orders import (
    CAPTURABLE_STATES,
    IllegalOrderTransition,
    Order,
    OrderValidationError,
    SettlementRequest,
)
from app.payment_port.mock_adapter import MockPaymentAdapter
from app.payment_port.port import (
    CheckoutSession,
    IdempotencyMismatch,
    InvalidPaymentRequest,
    PaymentPort,
    PaymentResult,
    ProviderEvent,
    TransientPaymentError,
)
from zeo_common import ApiError
from zeo_common.auth import Principal
from zeo_common.circuit_breaker import CircuitBreaker, CircuitOpen

logger = logging.getLogger(__name__)

AUTHORIZATION_EVENTS = frozenset({"payment.authorized", "payment.captured"})
# An order left AUTHORIZED this long (the process died between authorisation and capture) is
# picked up by the retrier; capture is idempotent, so this can never capture twice.
STUCK_AUTHORIZATION = timedelta(minutes=2)
MAX_SAVE_ATTEMPTS = 3


class PaymentMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.steps = Counter("settlement_steps", "Committed settlement steps, by step.",
                             ["step"], registry=registry)
        self.publish_failures = Counter(
            "payment_events_publish_failures",
            "Settlement steps committed but not published to payment.events.", registry=registry)
        self.capture_failures = Counter(
            "payment_capture_failures", "Captures parked in AWAITING_CAPTURE_RETRY, by reason.",
            ["reason"], registry=registry)
        self.webhooks = Counter("payment_webhooks", "Verified provider webhooks, by outcome.",
                                ["provider", "outcome"], registry=registry)


@dataclass(frozen=True)
class Checkout:
    order: Order
    session: CheckoutSession
    # Mock adapter only: the payment the simulated Checkout would return, so the demo can pay
    # without Razorpay. None with a real provider.
    simulated_payment: tuple[str, str] | None = None


def capture_breaker(clock: Callable[[], float] = time.monotonic) -> CircuitBreaker:
    """Orchestration -> Payment (capture), SDD Table 2.2 and settlement-policy capture_retry."""
    return CircuitBreaker("payment-capture", failure_threshold=3, window_seconds=30,
                          reset_seconds=10, clock=clock)


def payment_error(exc: Exception) -> ApiError:
    if isinstance(exc, TransientPaymentError | CircuitOpen):
        return ApiError("PAYMENT_PROVIDER_UNAVAILABLE",
                        "The payment provider is unavailable; try again shortly", 503)
    return ApiError("PAYMENT_PROVIDER_ERROR", "The payment provider refused the request", 502)


class PaymentService:
    def __init__(
        self,
        repo: PaymentRepository,
        port: PaymentPort,
        publisher: SettlementEventPublisher,
        metrics: PaymentMetrics,
        *,
        breaker: CircuitBreaker | None = None,
        payment_window: timedelta = timedelta(hours=48),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.port = port
        self.publisher = publisher
        self.metrics = metrics
        self.breaker = breaker or capture_breaker()
        self.payment_window = payment_window
        self.clock = clock

    # ------------------------------------------------------------------ helpers

    async def _publish(self, order: Order, step: str) -> None:
        self.metrics.steps.labels(step=step).inc()
        event = build_settlement_step(event_id=uuid4(), order=order, step=step,
                                      occurred_at=order.updated_at)
        try:
            await self.publisher.publish(event)
        except Exception:
            self.metrics.publish_failures.inc()
            logger.exception("Publishing %s for order %s failed", step, order.id)

    async def _load(self, order_id: UUID) -> Order:
        order = await self.repo.get(order_id)
        if order is None:
            raise ApiError("NOT_FOUND", f"Order {order_id} does not exist", 404)
        return order

    @staticmethod
    def _check_party(order: Order, principal: Principal) -> None:
        if not (principal.is_admin or order.party(principal.user_id)):
            raise ApiError("FORBIDDEN", "Only the buyer, the seller or an administrator can "
                           "see this order", 403)

    @staticmethod
    def _check_buyer(order: Order, principal: Principal) -> None:
        if principal.user_id != order.buyer_id:
            raise ApiError("FORBIDDEN", "Only the winning bidder can pay this order", 403)

    # ------------------------------------------------------------------ reads

    async def quote(self, bid_amount: Decimal) -> FeeQuote:
        try:
            return quote(bid_amount, await self.repo.active_fee())
        except FeeError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422, {"field": "bid_amount"}) from exc

    async def order_for(self, principal: Principal, order_id: UUID) -> tuple[Order, Invoice]:
        order = await self._load(order_id)
        self._check_party(order, principal)
        invoice = await self.repo.invoice(order.id)
        assert invoice is not None, "every order is created with its invoice"  # noqa: S101
        return order, invoice

    async def order_for_auction(self, principal: Principal,
                                auction_id: UUID) -> tuple[Order, Invoice]:
        order = await self.repo.by_auction(auction_id)
        if order is None:
            raise ApiError("NOT_FOUND", f"Auction {auction_id} has no order", 404)
        return await self.order_for(principal, order.id)

    async def ledger(self, order_id: UUID) -> list[LedgerEntry]:
        await self._load(order_id)
        return await self.repo.ledger(order_id)

    # ------------------------------------------------------------------ S1

    async def open_order(self, request: SettlementRequest) -> tuple[Order, bool]:
        """S1, called by Auction Orchestration. Idempotent per auction: a retry returns the
        order already opened (``created`` False) and invoices nobody twice."""
        existing = await self.repo.by_auction(request.auction_id)
        if existing is None:
            now = self.clock()
            try:
                order = machine.open_order(
                    request, order_id=uuid4(), saga_id=uuid4(),
                    fee=await self.repo.active_fee(), provider=self.port.provider, now=now,
                    payment_window=self.payment_window)
            except OrderValidationError as exc:
                raise ApiError("VALIDATION_ERROR", str(exc), 422) from exc
            existing, created = await self.repo.create_order(
                order, issue_invoice(order, invoice_id=uuid4()))
            if created:
                await self._publish(existing, "INVOICED")
                return existing, True
        if existing.winning_bid_id != request.winning_bid_id:
            raise ApiError("SETTLEMENT_CONFLICT", "The auction already has an order for a "
                           "different winning bid", 409, {"order_id": str(existing.id)})
        return existing, False

    # ------------------------------------------------------------------ Checkout

    async def start_checkout(self, principal: Principal, order_id: UUID) -> Checkout:
        order = await self._load(order_id)
        self._check_buyer(order, principal)
        if order.state not in machine.PAYABLE_STATES:
            raise ApiError("ORDER_NOT_PAYABLE", f"Order is {order.state}; there is nothing to "
                           "pay", 409, {"state": order.state})
        if order.provider_order_id is None:
            invoice = await self.repo.invoice(order.id)
            receipt = invoice.invoice_number if invoice else str(order.id)
            try:
                session = await self.port.create_checkout(order.id, order.captured_total,
                                                          order.currency, receipt)
            except (TransientPaymentError, InvalidPaymentRequest) as exc:
                logger.warning("Opening checkout for order %s failed: %s", order.id, exc)
                raise payment_error(exc) from exc
            try:
                order = await self._save(order, machine.attach_checkout(
                    order, session.provider_order_id, self.clock()))
            except StaleOrder:
                # A concurrent request attached its provider order first; pay that one.
                order = await self._load(order_id)
                if order.provider_order_id is None:
                    raise
        session = CheckoutSession(
            provider=order.provider, provider_order_id=order.provider_order_id,
            amount=order.captured_total, currency=order.currency,
            key_id=getattr(self.port, "key_id", None),
        )
        simulated = None
        if isinstance(self.port, MockPaymentAdapter):
            simulated = self.port.simulate_payment(session.provider_order_id)
        return Checkout(order=order, session=session, simulated_payment=simulated)

    async def confirm_payment(self, principal: Principal, order_id: UUID,
                              provider_order_id: str, payment_id: str,
                              signature: str) -> Order:
        """The browser hands back Checkout's signed result; verify it, then capture."""
        order = await self._load(order_id)
        self._check_buyer(order, principal)
        if order.provider_order_id is None or provider_order_id != order.provider_order_id:
            raise ApiError("PAYMENT_SIGNATURE_INVALID", "The payment is not for this order", 400)
        try:
            self.port.verify_checkout(provider_order_id, payment_id, signature)
        except InvalidPaymentRequest as exc:
            raise ApiError("PAYMENT_SIGNATURE_INVALID", "The payment signature is invalid",
                           400) from exc
        return await self._on_authorized(order, payment_id)

    async def handle_webhook(self, provider: str, payload: bytes,
                             headers: Mapping[str, str]) -> str:
        if provider != self.port.provider:
            raise ApiError("NOT_FOUND", f"No {provider} webhook on this deployment", 404)
        try:
            event = self.port.verify_webhook(payload, headers)
        except InvalidPaymentRequest as exc:
            logger.warning("Refused a %s webhook: %s", provider, exc)
            raise ApiError("WEBHOOK_SIGNATURE_INVALID", "Webhook verification failed",
                           400) from exc
        if not await self.repo.record_provider_event(event):
            self.metrics.webhooks.labels(provider=provider, outcome="duplicate").inc()
            return "duplicate"
        outcome = await self._apply_event(event)
        await self.repo.mark_event_processed(event, self.clock())
        self.metrics.webhooks.labels(provider=provider, outcome=outcome).inc()
        return outcome

    async def _apply_event(self, event: ProviderEvent) -> str:
        if event.event_type not in AUTHORIZATION_EVENTS:
            return "ignored"
        order = (await self.repo.by_provider_order(event.provider_order_id)
                 if event.provider_order_id else None)
        if order is None or not event.provider_ref:
            logger.info("Webhook %s refers to no known order", event.event_id)
            return "ignored"
        if event.amount is not None and (event.amount, event.currency) != (
                order.captured_total, order.currency):
            logger.error("Webhook %s amount %s %s does not match order %s", event.event_id,
                         event.amount, event.currency, order.id)
            return "ignored"
        await self._on_authorized(order, event.provider_ref)
        return "applied"

    # ------------------------------------------------------------------ S2-S3

    async def _save(self, before: Order, after: Order, *, entries: Sequence[LedgerEntry] = (),
                    void_invoice_at: datetime | None = None) -> Order:
        await self.repo.save(before, after, entries=entries, void_invoice_at=void_invoice_at)
        return after

    async def _on_authorized(self, order: Order, payment_id: str) -> Order:
        """Record the authorisation (once, whichever of the browser and the webhook arrives
        first), then capture. The loser of that race re-reads and leaves capture to the winner."""
        if order.state != "INVOICED":
            if order.provider_payment_id not in (None, payment_id):
                logger.warning("Order %s is already paid by %s; ignoring payment %s",
                               order.id, order.provider_payment_id, payment_id)
            return order
        try:
            order = await self._save(order, machine.authorize(order, payment_id, self.clock()))
        except StaleOrder:
            return await self._load(order.id)
        return await self.capture(order)

    async def _attempt_capture(self, order: Order) -> PaymentResult | Exception:
        """Capture through the breaker. Only transient failures count against it; a
        definitive refusal is returned, not raised."""
        async def attempt() -> PaymentResult | Exception:
            try:
                return await self.port.capture(
                    order.provider_payment_id, order.captured_total, order.currency,
                    order.idempotency_key("capture"))
            except (InvalidPaymentRequest, IdempotencyMismatch) as exc:
                return exc
        return await self.breaker.call(attempt)

    async def capture(self, order: Order) -> Order:
        if order.state not in CAPTURABLE_STATES:
            raise IllegalOrderTransition("capture", order.state)
        try:
            outcome = await self._attempt_capture(order)
        except (TransientPaymentError, CircuitOpen) as exc:
            reason = "breaker_open" if isinstance(exc, CircuitOpen) else "transient"
            self.metrics.capture_failures.labels(reason=reason).inc()
            logger.warning("Capture of order %s deferred (%s): %s", order.id, reason, exc)
            return await self._save(order, machine.capture_failed(order, self.clock()))
        if isinstance(outcome, Exception) or not outcome.succeeded:
            why = outcome if isinstance(outcome, Exception) else outcome.decline_reason
            logger.error("Capture of order %s failed definitively: %s", order.id, why)
            return await self.compensate(order)
        now = self.clock()
        captured = machine.capture_succeeded(order, outcome.provider_ref, now)
        await self._save(order, captured, entries=[capture_entry(captured, outcome.provider_ref)])
        await self._publish(captured, "CAPTURED")
        held = machine.hold(captured, now)
        await self._save(captured, held, entries=hold_entries(held))
        await self._publish(held, "HELD")
        return held

    async def compensate(self, order: Order) -> Order:
        """O4: CANCELLED with the invoice voided. Nothing was captured, so the ledger is
        untouched; an uncaptured authorisation lapses at the provider and returns to the buyer."""
        now = self.clock()
        cancelled = await self._save(order, machine.cancel(order, now), void_invoice_at=now)
        await self._publish(cancelled, "COMPENSATED")
        return cancelled

    # ------------------------------------------------------------------ background

    async def run_due_work(self, limit: int = 50) -> list[tuple[UUID, str]]:
        """One pass of the settlement worker: retry parked captures and resume captures a
        crash interrupted. Each order is handled independently; a lost race is skipped."""
        done = []
        now = self.clock()
        for order in await self.repo.due_capture_retries(now, limit):
            done.append(await self._guarded(order, self.capture))
        for order in await self.repo.stuck_authorizations(now - STUCK_AUTHORIZATION, limit):
            done.append(await self._guarded(order, self.capture))
        for order in await self.repo.unpaid_past_window(now, limit):
            done.append(await self._guarded(order, self.compensate))
        return [item for item in done if item is not None]

    async def _guarded(self, order: Order, step: Callable) -> tuple[UUID, str] | None:
        try:
            after = await step(order)
        except (StaleOrder, IllegalOrderTransition) as exc:
            logger.info("Settlement work on order %s skipped: %s", order.id, exc)
            return None
        return order.id, after.state

