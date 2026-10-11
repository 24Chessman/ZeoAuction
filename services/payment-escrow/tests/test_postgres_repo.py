"""The PostgreSQL repository's statements, against a recording fake of asyncpg."""

from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest

from app.adapters.repository import PostgresPaymentRepository, StaleOrder
from app.domain import orders as machine
from app.domain.invoice import issue_invoice
from app.domain.ledger import EntryType, LedgerError, capture_entry, hold_entries
from app.payment_port.port import ProviderEvent
from tests.support import NOW, order


class FakePool:
    def __init__(self, *, status="UPDATE 1", rows=None, value="inserted"):
        self.log = []
        self.status = status
        self.rows = rows or []
        self.value = value

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        self.log.append("BEGIN")
        try:
            yield
        except BaseException:
            self.log.append("ROLLBACK")
            raise
        self.log.append("COMMIT")

    async def execute(self, sql, *args):
        self.log.append((sql, args))
        return self.status if sql.startswith("UPDATE orders") else "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        self.log.append((sql, args))
        return self.rows[0] if self.rows else None

    async def fetchval(self, sql, *args):
        self.log.append((sql, args))
        return self.value

    async def fetch(self, sql, *args):
        self.log.append((sql, args))
        return self.rows

    def statements(self):
        return [entry[0] for entry in self.log if isinstance(entry, tuple)]


def order_row(o):
    row = dict(o.__dict__)
    row["currency"] = o.currency + ""  # char(3) arrives padded only if shorter; INR is exact
    return row


async def test_active_fee_reads_the_single_active_row():
    pool = FakePool(rows=[{"fee_version": "2026-10-v1", "convenience_fee": Decimal("99.00"),
                           "currency": "INR", "protection_window_days": 7}])
    fee = await PostgresPaymentRepository(pool).active_fee()
    assert (fee.fee_version, fee.convenience_fee, fee.currency) == (
        "2026-10-v1", Decimal("99.00"), "INR")
    assert "WHERE active" in pool.statements()[0]
    with pytest.raises(RuntimeError):
        await PostgresPaymentRepository(FakePool()).active_fee()


async def test_create_order_inserts_order_and_invoice_in_one_transaction():
    pool = FakePool()
    o = order()
    saved, created = await PostgresPaymentRepository(pool).create_order(
        o, issue_invoice(o, invoice_id=uuid4()))
    assert created and saved == o
    assert pool.log[0] == "BEGIN" and pool.log[-1] == "COMMIT"
    insert_order, insert_invoice = pool.statements()
    assert "ON CONFLICT (auction_id) DO NOTHING" in insert_order
    assert insert_invoice.startswith("INSERT INTO invoices")


async def test_create_order_returns_the_existing_order_on_conflict():
    existing = order()
    pool = FakePool(value=None, rows=[order_row(existing)])
    saved, created = await PostgresPaymentRepository(pool).create_order(
        order(), issue_invoice(existing, invoice_id=uuid4()))
    assert not created and saved == existing
    assert not any(s.startswith("INSERT INTO invoices") for s in pool.statements())


async def test_lookups_round_trip_rows():
    o = order()
    repo = PostgresPaymentRepository(FakePool(rows=[order_row(o)]))
    assert await repo.get(o.id) == o
    assert await repo.by_auction(o.auction_id) == o
    assert await repo.by_provider_order("order_X") == o
    assert await PostgresPaymentRepository(FakePool()).get(o.id) is None
    invoice = issue_invoice(o, invoice_id=uuid4())
    repo = PostgresPaymentRepository(FakePool(rows=[dict(invoice.__dict__)]))
    assert await repo.invoice(o.id) == invoice
    assert await PostgresPaymentRepository(FakePool()).invoice(o.id) is None


async def test_save_checks_the_version_and_appends_ledger_rows_atomically():
    pool = FakePool()
    authorized = machine.authorize(order(), "pay_1", NOW)
    captured = machine.capture_succeeded(authorized, "pay_1", NOW)
    await PostgresPaymentRepository(pool).save(authorized, captured,
                                               entries=[capture_entry(captured, "pay_1")])
    statements = pool.statements()
    assert statements[0].startswith("SELECT") and "FROM escrow_ledger" in statements[0]
    update = next(entry for entry in pool.log if isinstance(entry, tuple)
                  and entry[0].startswith("UPDATE orders"))
    assert update[1][-2:] == (authorized.id, authorized.version)
    assert statements[2].startswith("INSERT INTO escrow_ledger")
    assert pool.log[-1] == "COMMIT"


async def test_save_without_entries_skips_the_ledger_and_can_void_the_invoice():
    pool = FakePool()
    o = order()
    await PostgresPaymentRepository(pool).save(o, machine.cancel(o, NOW), void_invoice_at=NOW)
    statements = pool.statements()
    assert statements[0].startswith("UPDATE orders")
    assert statements[1].startswith("UPDATE invoices SET voided_at")


async def test_a_lost_race_rolls_back():
    pool = FakePool(status="UPDATE 0")
    o = order()
    with pytest.raises(StaleOrder):
        await PostgresPaymentRepository(pool).save(o, machine.cancel(o, NOW))
    assert pool.log[-1] == "ROLLBACK"


async def test_ledger_rows_breaking_an_invariant_are_never_sent():
    captured = machine.capture_succeeded(machine.authorize(order(), "p", NOW), "p", NOW)
    existing = {**capture_entry(captured, "p").__dict__, "id": 1, "created_at": NOW,
                "entry_type": "CAPTURE"}
    pool = FakePool(rows=[existing])
    held = machine.hold(captured, NOW)
    with pytest.raises(LedgerError):
        await PostgresPaymentRepository(pool).save(captured, held,
                                                   entries=[capture_entry(held, "p")])
    assert not any(s.startswith("UPDATE") for s in pool.statements())
    repo = PostgresPaymentRepository(FakePool(rows=[existing]))
    rows = await repo.ledger(captured.id)
    assert rows[0].entry_type is EntryType.CAPTURE and rows[0].id == 1
    assert len(hold_entries(held)) == 2


async def test_provider_events_are_recorded_once_and_marked_processed():
    event = ProviderEvent("razorpay", "evt_1", "payment.authorized")
    fresh = FakePool(rows=[{"processed_at": None}])
    assert await PostgresPaymentRepository(fresh).record_provider_event(event)
    assert "ON CONFLICT (provider, event_id)" in fresh.statements()[0]
    done = FakePool(rows=[{"processed_at": NOW}])
    assert not await PostgresPaymentRepository(done).record_provider_event(event)
    pool = FakePool()
    await PostgresPaymentRepository(pool).mark_event_processed(event, NOW)
    assert pool.log[0][1] == (NOW, "razorpay", "evt_1")


@pytest.mark.parametrize("scan, state", [
    ("due_capture_retries", "AWAITING_CAPTURE_RETRY"),
    ("stuck_authorizations", "AUTHORIZED"),
    ("unpaid_past_window", "INVOICED"),
])
async def test_worker_scans(scan, state):
    o = order()
    pool = FakePool(rows=[order_row(o)])
    assert await getattr(PostgresPaymentRepository(pool), scan)(NOW, 10) == [o]
    sql, args = pool.log[0]
    assert f"state = '{state}'" in sql and args == (NOW, 10)
