"""Payment, Fees & Escrow routes (SDD 7.4; contract contracts/openapi/payment.v1.yaml).

Test mode only: no real money moves, and every order view says so (``test_mode``).

* ``GET /fees/quote``: public pre-bid disclosure (AC-07), from the active ``fee_config``.
* ``POST /internal/orders``: S1, called by Auction Orchestration only (internal contract
  ``contracts/openapi/internal/settlement.v1.yaml``), authenticated by ``X-Internal-Token``.
* ``GET /orders/{id}``, ``GET /auctions/{id}/order``: the buyer, the seller or an admin.
* ``POST /orders/{id}/checkout`` and ``POST /orders/{id}/payment``: the winner pays in
  Razorpay Checkout, then hands back the signed result; capture and the escrow hold follow.
* ``POST /webhooks/{provider}``: signed provider webhooks (``payment.authorized``), FR-PAY-7.
* ``GET /orders/{id}/ledger``: administrators read the append-only escrow ledger.
"""

import hmac
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.domain.invoice import Invoice
from app.domain.orders import Order, SettlementRequest
from app.payment_port.razorpay_adapter import to_paise
from app.service import PaymentService
from zeo_common import ApiError, format_money, parse_money
from zeo_common.auth import AdminPrincipal, CurrentPrincipal
from zeo_common.money import MONEY_PATTERN

router = APIRouter(prefix="/api/v1", tags=["payments"])

MoneyStr = Annotated[str, Field(pattern=MONEY_PATTERN, examples=["1250.00"])]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]
TEST_MODE_NOTICE = "Test mode: escrow is a simulation and no real money moves."


def get_service(request: Request) -> PaymentService:
    return request.app.state.payment_service


Service = Annotated[PaymentService, Depends(get_service)]


async def internal_caller(
    request: Request, token: Annotated[str, Header(alias="X-Internal-Token")] = "",
) -> None:
    expected: str = request.app.state.internal_token
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise ApiError("UNAUTHENTICATED", "Internal route: a service token is required", 401)


InternalCaller = Depends(internal_caller)


# ---------------------------------------------------------------------- views


class FeeQuoteView(BaseModel):
    bid_amount: str = Field(examples=["1250.00"])
    convenience_fee: str = Field(examples=["99.00"])
    total: str = Field(examples=["1349.00"])
    currency: str = Field(examples=["INR"])
    fee_version: str = Field(
        description="The fee_config row in force; disclosure, invoice and settlement agree.",
        examples=["2026-10-v1"],
    )


class InvoiceView(BaseModel):
    invoice_number: str
    bid_amount: str
    convenience_fee: str
    total: str
    currency: str
    fee_version: str
    issued_at: datetime
    voided_at: datetime | None


class OrderView(BaseModel):
    order_id: UUID
    auction_id: UUID
    buyer_id: UUID
    seller_id: UUID
    winning_bid_id: UUID
    state: str
    winning_bid_amount: str
    convenience_fee: str
    total: str
    currency: str
    fee_version: str
    provider: str
    payment_due_at: datetime | None
    authorized_at: datetime | None
    created_at: datetime
    updated_at: datetime
    invoice: InvoiceView
    test_mode: Literal[True] = True
    notice: str = TEST_MODE_NOTICE


class SettlementRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auction_id: UUID
    buyer_id: UUID
    seller_id: UUID
    winning_bid_id: UUID
    winning_bid_amount: MoneyStr
    currency: str = Field(pattern=r"^[A-Z]{3}$", examples=["INR"])


class SimulatedPayment(BaseModel):
    payment_id: str
    signature: str


class CheckoutView(BaseModel):
    order_id: UUID
    provider: str = Field(examples=["razorpay"])
    key_id: str | None = Field(description="Public key to open Checkout with (rzp_test_...).")
    provider_order_id: str = Field(examples=["order_PQ12abcXYZ"])
    amount: str = Field(examples=["1349.00"])
    amount_minor: int = Field(description="The amount in paise, as Checkout expects it.",
                              examples=[134900])
    currency: str
    description: str
    simulated_payment: SimulatedPayment | None = Field(
        default=None, description="Mock adapter only: what the simulated Checkout returns.")
    test_mode: Literal[True] = True


class PaymentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_order_id: str = Field(min_length=1, max_length=64)
    payment_id: str = Field(min_length=1, max_length=64)
    signature: str = Field(min_length=1, max_length=256)


class LedgerEntryView(BaseModel):
    id: int | None
    entry_type: str
    amount: str
    currency: str
    idempotency_key: str
    provider_ref: str | None
    note: str | None
    created_at: datetime | None


class WebhookAck(BaseModel):
    outcome: Literal["applied", "ignored", "duplicate"]


def money(value) -> str:
    return format_money(value)


def invoice_view(invoice: Invoice) -> InvoiceView:
    return InvoiceView(
        invoice_number=invoice.invoice_number, bid_amount=money(invoice.bid_amount),
        convenience_fee=money(invoice.convenience_fee), total=money(invoice.total),
        currency=invoice.currency, fee_version=invoice.fee_version,
        issued_at=invoice.issued_at, voided_at=invoice.voided_at,
    )


def order_view(order: Order, invoice: Invoice) -> OrderView:
    return OrderView(
        order_id=order.id, auction_id=order.auction_id, buyer_id=order.buyer_id,
        seller_id=order.seller_id, winning_bid_id=order.winning_bid_id, state=order.state,
        winning_bid_amount=money(order.winning_bid_amount),
        convenience_fee=money(order.convenience_fee), total=money(order.captured_total),
        currency=order.currency, fee_version=order.fee_version, provider=order.provider,
        payment_due_at=order.payment_due_at, authorized_at=order.authorized_at,
        created_at=order.created_at, updated_at=order.updated_at,
        invoice=invoice_view(invoice),
    )


# ---------------------------------------------------------------------- routes


@router.get("/fees/quote", response_model=FeeQuoteView, operation_id="quoteFee")
async def quote_fee(
    bid_amount: Annotated[str, Query(pattern=MONEY_PATTERN, examples=["1250.00"])],
    response: Response,
    service: Service,
) -> FeeQuoteView:
    """Public: the flat fee and resulting total, shown before a bid is placed (AC-07)."""
    result = await service.quote(parse_money(bid_amount))
    # Same answer for every caller until the fee_version changes.
    response.headers["Cache-Control"] = "public, max-age=60"
    return FeeQuoteView(
        bid_amount=money(result.bid_amount), convenience_fee=money(result.convenience_fee),
        total=money(result.total), currency=result.currency, fee_version=result.fee_version,
    )


@router.post("/internal/orders", response_model=OrderView, operation_id="openOrder",
             dependencies=[InternalCaller], tags=["internal"])
async def open_order(
    body: SettlementRequestBody, idempotency_key: IdempotencyKey, response: Response,
    service: Service,
) -> OrderView:
    """S1: order and invoice for the winning bid. 201 when created, 200 for a retry."""
    order, created = await service.open_order(SettlementRequest(
        auction_id=body.auction_id, buyer_id=body.buyer_id, seller_id=body.seller_id,
        winning_bid_id=body.winning_bid_id,
        winning_bid_amount=parse_money(body.winning_bid_amount), currency=body.currency,
    ))
    response.status_code = 201 if created else 200
    invoice = await service.repo.invoice(order.id)
    return order_view(order, invoice)


@router.get("/orders/{order_id}", response_model=OrderView, operation_id="getOrder")
async def get_order(order_id: UUID, principal: CurrentPrincipal, service: Service) -> OrderView:
    return order_view(*await service.order_for(principal, order_id))


@router.get("/auctions/{auction_id}/order", response_model=OrderView,
            operation_id="getAuctionOrder")
async def get_auction_order(auction_id: UUID, principal: CurrentPrincipal,
                            service: Service) -> OrderView:
    return order_view(*await service.order_for_auction(principal, auction_id))


@router.post("/orders/{order_id}/checkout", response_model=CheckoutView,
             operation_id="startCheckout")
async def start_checkout(order_id: UUID, principal: CurrentPrincipal,
                         service: Service) -> CheckoutView:
    """The winner opens Checkout. Repeating it returns the same provider order."""
    checkout = await service.start_checkout(principal, order_id)
    session = checkout.session
    simulated = None
    if checkout.simulated_payment:
        payment_id, signature = checkout.simulated_payment
        simulated = SimulatedPayment(payment_id=payment_id, signature=signature)
    invoice = await service.repo.invoice(checkout.order.id)
    return CheckoutView(
        order_id=checkout.order.id, provider=session.provider, key_id=session.key_id,
        provider_order_id=session.provider_order_id, amount=money(session.amount),
        amount_minor=to_paise(session.amount), currency=session.currency,
        description=f"Invoice {invoice.invoice_number if invoice else checkout.order.id}"
                    " (test mode)",
        simulated_payment=simulated,
    )


@router.post("/orders/{order_id}/payment", response_model=OrderView,
             operation_id="confirmPayment")
async def confirm_payment(
    order_id: UUID, body: PaymentConfirmation, principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey, service: Service,
) -> OrderView:
    """Checkout's signed result: verified, then captured into escrow (S2, S3)."""
    order = await service.confirm_payment(principal, order_id, body.provider_order_id,
                                          body.payment_id, body.signature)
    return order_view(order, await service.repo.invoice(order.id))


@router.post("/webhooks/{provider}", response_model=WebhookAck, operation_id="providerWebhook",
             tags=["webhooks"])
async def provider_webhook(provider: str, request: Request, service: Service) -> WebhookAck:
    """Signed provider webhook. Answered 200 for anything verified, including events we
    ignore, so the provider stops redelivering; 400 for a bad signature."""
    outcome = await service.handle_webhook(provider, await request.body(), request.headers)
    return WebhookAck(outcome=outcome)


@router.get("/orders/{order_id}/ledger", response_model=list[LedgerEntryView],
            operation_id="getOrderLedger")
async def get_ledger(order_id: UUID, _: AdminPrincipal,
                     service: Service) -> list[LedgerEntryView]:
    return [
        LedgerEntryView(
            id=entry.id, entry_type=str(entry.entry_type), amount=money(entry.amount),
            currency=entry.currency, idempotency_key=entry.idempotency_key,
            provider_ref=entry.provider_ref, note=entry.note, created_at=entry.created_at,
        )
        for entry in await service.ledger(order_id)
    ]
