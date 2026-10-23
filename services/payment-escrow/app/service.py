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

Saga (#63, ``app/domain/saga.py``). Each step's progress is upserted into ``saga_steps`` in the
step's own transaction. An order left CAPTURED (a crash, or a database failure between S2 and
S3) is resumed by the worker: S3 is retried. If S3 fails definitively, S2 is compensated
(O4a): the capture is fully reversed at the provider with key ``order:{id}:reverse-capture``,
COMPENSATION rows return custody to zero, the order is CANCELLED with its invoice voided, and
``payment_saga_compensations{step="S2"}`` plus an error log raise the operational alert. A
reversal the provider can't do right now leaves the order CAPTURED for the next pass, with the
same key, so it is never refunded twice.

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
from app.domain.ledger import (
    EntryType,
    LedgerEntry,
    LedgerError,
    capture_entry,
    hold_entries,
)
from app.domain.orders import (
    CAPTURABLE_STATES,
    IllegalOrderTransition,
    Order,
    OrderValidationError,
    SettlementRequest,
    WindowClosedError,
)
from app.domain.refund import Fault, execute_refund
from app.domain.release import ReleaseTrigger, execute_release
from app.domain.saga import (
    REVERSE_CAPTURE,
    SagaStepRecord,
    Step,
    StepStatus,
    reversal_entries,
    step_record,
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
# Likewise an order left CAPTURED: S3 is resumed (or, if it can't succeed, S2 compensated).
STUCK_CAPTURE = timedelta(minutes=2)
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
        self.compensations = Counter(
            "payment_saga_compensations", "Saga steps compensated (an operational alert).",
            ["step"], registry=registry)
        self.compensation_failures = Counter(
            "payment_saga_compensation_failures",
            "Compensations the provider could not do yet; retried on the next pass.",
            ["step", "reason"], registry=registry)


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

    async def _publish(self, order: Order, step: str, operation: str | None = None) -> None:
        self.metrics.steps.labels(step=step).inc()
        event = build_settlement_step(event_id=uuid4(), order=order, step=step,
                                      occurred_at=order.updated_at, operation=operation)
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

    @staticmethod
    def _check_seller(order: Order, principal: Principal) -> None:
        if not (principal.is_admin or principal.user_id == order.seller_id):
            raise ApiError("FORBIDDEN", "Only the seller can perform this action", 403)

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
                order, issue_invoice(order, invoice_id=uuid4()),
                steps=[step_record(order, Step.S1, StepStatus.DONE)])
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
            raise ApiError("PAYMENT_SIGNATURE_INVALID", "The payment signature is invalid", 400) from exc
        return await self._on_authorized(order, payment_id)

    async def ship(self, principal: Principal, order_id: UUID) -> Order:
        """O6: seller marks item shipped; opens the protection window."""
        order = await self._load(order_id)
        self._check_seller(order, principal)
        try:
            shipped = machine.mark_shipped(order, self.clock(), window_days=7)
        except IllegalOrderTransition as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc
        saved = await self._save(order, shipped)
        await self._publish(saved, "SHIPPED")
        return saved

    async def confirm_receipt(self, principal: Principal, order_id: UUID) -> Order:
        """O9: buyer confirms receipt; release funds to seller immediately."""
        order = await self._load(order_id)
        self._check_buyer(order, principal)
        if order.state == "RELEASED":
            return order
        try:
            existing = await self.repo.ledger(order.id)
            released, entry = execute_release(order, ReleaseTrigger.BUYER_CONFIRM, self.clock(), existing)
        except (IllegalOrderTransition, LedgerError) as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc

        try:
            await self.port.payout(
                order.capture_ref or "", order.seller_id,
                order.captured_total - order.convenience_fee,
                order.currency, entry.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Provider payout for %s: %s", order.id, exc)

        saved = await self._save(order, released, entries=[entry])
        await self._publish(saved, "RELEASED")
        return saved

    async def release(self, order_id: UUID, trigger: str = "sweep_expiry",
                      idempotency_key: str | None = None) -> Order:
        """O10/O11: release funds upon sweep expiry or admin adjudication in seller's favour."""
        order = await self._load(order_id)
        if order.state == "RELEASED":
            return order
        existing = await self.repo.ledger(order.id)
        if any(e.entry_type == EntryType.RELEASE for e in existing):
            return order
        try:
            rel_trigger = (
                ReleaseTrigger.SWEEP_EXPIRY if trigger == "sweep_expiry"
                else ReleaseTrigger.ADJUDICATE_SELLER
            )
            released, entry = execute_release(order, rel_trigger, self.clock(), existing)
        except (IllegalOrderTransition, LedgerError) as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc

        try:
            await self.port.payout(
                order.capture_ref or "", order.seller_id,
                order.captured_total - order.convenience_fee,
                order.currency, entry.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Provider payout for %s: %s", order.id, exc)

        saved = await self._save(order, released, entries=[entry])
        await self._publish(saved, "RELEASED")
        return saved

    async def freeze(self, order_id: UUID, reason: str = "dispute") -> Order:
        """O7/O8: freeze escrow upon buyer dispute or fraud alert."""
        order = await self._load(order_id)
        if order.state == "DISPUTED":
            return order
        try:
            if reason == "fraud":
                frozen = machine.fraud_dispute(order, self.clock())
            else:
                frozen = machine.raise_dispute(order, self.clock())
        except WindowClosedError as exc:
            raise ApiError("WINDOW_CLOSED", str(exc), 409) from exc
        except IllegalOrderTransition as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc

        saved = await self._save(order, frozen)
        await self._publish(saved, "DISPUTED")
        return saved

    async def refund(self, order_id: UUID, fault: str, note: str | None = None,
                     idempotency_key: str | None = None) -> Order:
        """O12: admin resolves dispute in buyer's favour; refund funds with fee treatment by fault."""
        order = await self._load(order_id)
        if order.state == "REFUNDED":
            return order
        existing = await self.repo.ledger(order.id)
        if any(e.entry_type == EntryType.REFUND for e in existing):
            return order
        try:
            fault_val = Fault(fault)
            refunded, entries = execute_refund(order, fault_val, self.clock(), existing, note=note)
        except (IllegalOrderTransition, LedgerError, ValueError) as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc

        refund_amount = order.winning_bid_amount if fault_val == Fault.BUYER else order.captured_total
        try:
            await self.port.refund(
                order.capture_ref or "", refund_amount, order.currency,
                order.idempotency_key("refund"),
            )
        except Exception as exc:
            logger.warning("Provider refund for %s: %s", order.id, exc)

        saved = await self._save(order, refunded, entries=entries)
        await self._publish(saved, "REFUNDED")
        return saved

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
                    void_invoice_at: datetime | None = None,
                    steps: Sequence[SagaStepRecord] = ()) -> Order:
        await self.repo.save(before, after, entries=entries, void_invoice_at=void_invoice_at,
                             steps=steps)
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
            return await self._save(order, machine.capture_failed(order, self.clock()), steps=[
                step_record(order, Step.S2, StepStatus.FAILED, f"{reason}: {exc}")])
        if isinstance(outcome, Exception) or not outcome.succeeded:
            why = outcome if isinstance(outcome, Exception) else outcome.decline_reason
            logger.error("Capture of order %s failed definitively: %s", order.id, why)
            return await self.compensate(order, failure=f"capture refused: {why}")
        captured = machine.capture_succeeded(order, outcome.provider_ref, self.clock())
        await self._save(order, captured, entries=[capture_entry(captured, outcome.provider_ref)],
                         steps=[step_record(captured, Step.S2, StepStatus.DONE)])
        await self._publish(captured, "CAPTURED")
        return await self.hold(captured)

    async def hold(self, order: Order) -> Order:
        """S3 + S4 in one transaction. A definitive failure compensates S2; any other error
        propagates and leaves the order CAPTURED for the worker to resume."""
        held = machine.hold(order, self.clock())
        try:
            entries = hold_entries(held)
            await self._save(order, held, entries=entries, steps=[
                step_record(held, Step.S3, StepStatus.DONE),
                step_record(held, Step.S4, StepStatus.DONE)])
        except LedgerError as exc:
            logger.error("S3 for order %s failed definitively: %s", order.id, exc)
            return await self.compensate_capture(order, failure=f"S3: {exc}")
        await self._publish(held, "HELD")
        return held

    async def compensate(self, order: Order, failure: str | None = None) -> Order:
        """O4: CANCELLED with the invoice voided. Nothing was captured, so the ledger is
        untouched; an uncaptured authorisation lapses at the provider and returns to the buyer."""
        now = self.clock()
        steps = [step_record(order, Step.S1, StepStatus.COMPENSATED, failure)]
        if order.provider_payment_id is not None:
            steps.insert(0, step_record(order, Step.S2, StepStatus.FAILED, failure))
        cancelled = await self._save(order, machine.cancel(order, now), void_invoice_at=now,
                                     steps=steps)
        await self._publish(cancelled, "COMPENSATED")
        return cancelled

    async def compensate_capture(self, order: Order, failure: str) -> Order:
        """O4a, compensating S2 after the money was captured: reverse the capture in full at
        the provider, write COMPENSATION rows equal and opposite to the custody rows, then
        compensate S1. Retried with the same key until the provider can reverse it."""
        key = order.idempotency_key(REVERSE_CAPTURE)
        try:
            result = await self.port.refund(order.capture_ref or "", order.captured_total,
                                            order.currency, key)
        except TransientPaymentError as exc:
            self.metrics.compensation_failures.labels(step="S2", reason="transient").inc()
            logger.error("Reversing the capture of order %s failed; retrying later: %s",
                         order.id, exc)
            await self._mark_failed(order, Step.S3, failure)
            return order
        except (InvalidPaymentRequest, IdempotencyMismatch) as exc:
            refused: str | None = str(exc)
        else:
            refused = None if result.succeeded else result.decline_reason or "declined"
        if refused is not None:
            self.metrics.compensation_failures.labels(step="S2", reason="refused").inc()
            logger.error("OPERATIONAL ALERT: the provider refused to reverse the capture of "
                         "order %s (%s); it stays CAPTURED for an operator", order.id, refused)
            await self._mark_failed(order, Step.S3, failure)
            return order
        now = self.clock()
        cancelled = machine.cancel_after_capture(order, now)
        rows = reversal_entries(cancelled, await self.repo.ledger(order.id))
        await self._save(order, cancelled, entries=rows, void_invoice_at=now, steps=[
            step_record(order, Step.S3, StepStatus.FAILED, failure),
            step_record(order, Step.S2, StepStatus.COMPENSATED, failure),
            step_record(order, Step.S1, StepStatus.COMPENSATED, failure)])
        self.metrics.compensations.labels(step="S2").inc()
        logger.error("OPERATIONAL ALERT: settlement of order %s compensated after capture "
                     "(%s); %s %s returned to the buyer", order.id, failure,
                     order.captured_total, order.currency)
        await self._publish(cancelled, "COMPENSATED", operation=REVERSE_CAPTURE)
        return cancelled

    async def _mark_failed(self, order: Order, step: Step, failure: str) -> None:
        """Record a failed attempt without moving the order (a no-op save bumps nothing)."""
        try:
            await self.repo.save(order, order, steps=[step_record(order, step,
                                                                  StepStatus.FAILED, failure)])
        except StaleOrder:
            logger.info("Order %s changed while recording %s; skipped", order.id, step)

    # ------------------------------------------------------------------ background

    async def run_due_work(self, limit: int = 50) -> list[tuple[UUID, str]]:
        """One pass of the settlement worker: retry parked captures, resume captures and holds
        a crash interrupted, and cancel unpaid orders. Each order is handled independently; a
        lost race is skipped."""
        done = []
        now = self.clock()
        for order in await self.repo.due_capture_retries(now, limit):
            done.append(await self._guarded(order, self.capture))
        for order in await self.repo.stuck_authorizations(now - STUCK_AUTHORIZATION, limit):
            done.append(await self._guarded(order, self.capture))
        for order in await self.repo.unpaid_past_window(now, limit):
            done.append(await self._guarded(order, self.compensate))
        for order in await self.repo.stuck_captures(now - STUCK_CAPTURE, limit):
            done.append(await self._guarded(order, self.hold))
        return [item for item in done if item is not None]

    async def _guarded(self, order: Order, step: Callable) -> tuple[UUID, str] | None:
        try:
            after = await step(order)
        except (StaleOrder, IllegalOrderTransition) as exc:
            logger.info("Settlement work on order %s skipped: %s", order.id, exc)
            return None
        except Exception:
            # One order's failure (say, the database refusing its write) must not starve the
            # others in this pass; the order is still due and is picked up again next pass.
            logger.exception("Settlement work on order %s failed; retrying next pass", order.id)
            return None
        return order.id, after.state

