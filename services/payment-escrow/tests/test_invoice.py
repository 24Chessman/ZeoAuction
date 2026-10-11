"""Invoice generation (#34): winning bid + flat fee, never for losing bidders (AC-09)."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.invoice import invoice_number, issue_invoice, void
from tests.support import NOW, order


def test_invoice_copies_the_order_amounts_and_fee_version():
    o = order("1250.00")
    invoice = issue_invoice(o, invoice_id=uuid4())
    assert (invoice.bid_amount, invoice.convenience_fee, invoice.total) == (
        Decimal("1250.00"), Decimal("99.00"), Decimal("1349.00"))
    assert (invoice.currency, invoice.fee_version, invoice.issued_at) == ("INR", "2026-10-v1", NOW)
    assert invoice.voided_at is None


def test_invoice_number_is_readable_and_unique_per_order():
    a, b = order(), order()
    assert invoice_number(a).startswith("ZA-202610-")
    assert len(invoice_number(a)) == len("ZA-202610-") + 12
    assert invoice_number(a) != invoice_number(b)


def test_an_inconsistent_order_cannot_be_invoiced():
    broken = replace(order(), captured_total=Decimal("1.00"))
    with pytest.raises(ValueError):
        issue_invoice(broken, invoice_id=uuid4())


def test_voiding_is_recorded_once():
    invoice = issue_invoice(order(), invoice_id=uuid4())
    voided = void(invoice, NOW)
    assert voided.voided_at == NOW
    assert void(voided, NOW.replace(year=2030)).voided_at == NOW
