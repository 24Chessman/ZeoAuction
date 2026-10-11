"""Invoice generation: winning bid plus the flat convenience fee (#34, FR-PAY-4, AC-09).

Pure logic, no I/O. An invoice is issued with its order in saga step S1 and copies the order's
amounts and ``fee_version``, so the invoice, the pre-bid quote and the ledger can never disagree.
There is exactly one invoice per order and one order per auction, for the winner: losing bidders
are never invoiced. Compensating S1 voids the invoice (``voided_at``); it is never deleted.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.orders import Order


@dataclass(frozen=True)
class Invoice:
    id: UUID
    order_id: UUID
    invoice_number: str
    bid_amount: Decimal
    convenience_fee: Decimal
    total: Decimal
    currency: str
    fee_version: str
    issued_at: datetime
    voided_at: datetime | None = None


def invoice_number(order: Order) -> str:
    """``ZA-YYYYMM-XXXXXXXXXXXX``: issue month plus the order id, readable on a receipt and
    unique because the order id is."""
    return f"ZA-{order.created_at:%Y%m}-{order.id.hex[:12].upper()}"


def issue_invoice(order: Order, *, invoice_id: UUID) -> Invoice:
    if order.captured_total != order.winning_bid_amount + order.convenience_fee:
        raise ValueError("invoice total must equal the winning bid plus the fee")
    return Invoice(
        id=invoice_id, order_id=order.id, invoice_number=invoice_number(order),
        bid_amount=order.winning_bid_amount, convenience_fee=order.convenience_fee,
        total=order.captured_total, currency=order.currency, fee_version=order.fee_version,
        issued_at=order.created_at,
    )


def void(invoice: Invoice, now: datetime) -> Invoice:
    return invoice if invoice.voided_at else replace(invoice, voided_at=now)
