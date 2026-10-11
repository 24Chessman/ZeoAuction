"""Payment persistence: PostgreSQL for real, in-memory for tests and database-less runs.

One repository owns the ``payment`` schema's settlement tables, because the saga's writes must
be atomic across them: an order's state change, the ledger rows it causes and a voided invoice
commit together or not at all.

* Orders use optimistic locking on ``version`` (state-machine rule 3): the UPDATE names the
  version it read, and 0 rows changed raises :class:`StaleOrder` so the caller re-reads.
* ``payment.orders.auction_id`` is unique, so an auction settles exactly once: opening an order
  for an auction that already has one returns the existing order (A7, "settle exactly once").
* The ledger is only ever INSERTed into (no UPDATE/DELETE grant, and a trigger). Rows are
  checked by :func:`app.domain.ledger.check_append` before they are written.
* Provider webhooks are recorded once per ``(provider, event_id)`` (FR-PAY-7).
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.fees import ACTIVE_FEE, FeeConfig
from app.domain.invoice import Invoice
from app.domain.ledger import EntryType, LedgerEntry, check_append
from app.domain.orders import Order
from app.payment_port.port import ProviderEvent

_ORDER_COLUMNS = (
    "id, auction_id, buyer_id, seller_id, winning_bid_id, winning_bid_amount, convenience_fee, "
    "captured_total, currency, fee_version, state, saga_id, provider, created_at, updated_at, "
    "version, provider_order_id, provider_payment_id, capture_ref, payment_due_at, "
    "authorized_at, capture_attempts, next_capture_at, shipped_at, protection_window_ends_at"
)
_INVOICE_COLUMNS = (
    "id, order_id, invoice_number, bid_amount, convenience_fee, total, currency, fee_version, "
    "issued_at, voided_at"
)
_LEDGER_COLUMNS = (
    "id, order_id, entry_type, amount, currency, idempotency_key, saga_id, compensates_id, "
    "provider_ref, note, created_at"
)
_UPDATE_ORDER = (
    "UPDATE orders SET state = $1, provider_order_id = $2, provider_payment_id = $3, "
    "capture_ref = $4, authorized_at = $5, capture_attempts = $6, next_capture_at = $7, "
    "shipped_at = $8, protection_window_ends_at = $9, version = $10, updated_at = $11 "
    "WHERE id = $12 AND version = $13"
)
_INSERT_LEDGER = (
    "INSERT INTO escrow_ledger (order_id, entry_type, amount, currency, idempotency_key, "
    "saga_id, compensates_id, provider_ref, note) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
)


class StaleOrder(Exception):
    """Another writer changed the order first; re-read and re-evaluate."""


class PaymentRepository(Protocol):
    async def active_fee(self) -> FeeConfig: ...

    async def create_order(self, order: Order, invoice: Invoice) -> tuple[Order, bool]:
        """Insert the order and its invoice; returns ``(order, created)``. If the auction
        already has an order, that one is returned with ``created`` False."""
        ...

    async def get(self, order_id: UUID) -> Order | None: ...

    async def by_auction(self, auction_id: UUID) -> Order | None: ...

    async def by_provider_order(self, provider_order_id: str) -> Order | None: ...

    async def invoice(self, order_id: UUID) -> Invoice | None: ...

    async def save(self, before: Order, after: Order, *,
                   entries: Sequence[LedgerEntry] = (),
                   void_invoice_at: datetime | None = None) -> None: ...

    async def ledger(self, order_id: UUID) -> list[LedgerEntry]: ...

    async def record_provider_event(self, event: ProviderEvent) -> bool:
        """Record a delivery; True while ``(provider, event_id)`` still needs processing, False
        for a redelivery of an event already processed."""
        ...

    async def mark_event_processed(self, event: ProviderEvent, now: datetime) -> None: ...

    async def due_capture_retries(self, now: datetime, limit: int) -> list[Order]: ...

    async def stuck_authorizations(self, authorized_before: datetime,
                                   limit: int) -> list[Order]:
        """AUTHORIZED orders whose capture a crash interrupted."""
        ...

    async def unpaid_past_window(self, now: datetime, limit: int) -> list[Order]:
        """INVOICED orders whose winner did not pay by ``payment_due_at``."""
        ...


class InMemoryPaymentRepository:
    def __init__(self, fee: FeeConfig = ACTIVE_FEE) -> None:
        self.fee = fee
        self.orders: dict[UUID, Order] = {}
        self.invoices: dict[UUID, Invoice] = {}
        self.entries: list[LedgerEntry] = []
        self.events: dict[tuple[str, str], datetime | None] = {}

    async def active_fee(self) -> FeeConfig:
        return self.fee

    async def create_order(self, order: Order, invoice: Invoice) -> tuple[Order, bool]:
        existing = await self.by_auction(order.auction_id)
        if existing is not None:
            return existing, False
        self.orders[order.id] = order
        self.invoices[order.id] = invoice
        return order, True

    async def get(self, order_id: UUID) -> Order | None:
        return self.orders.get(order_id)

    async def by_auction(self, auction_id: UUID) -> Order | None:
        return next((o for o in self.orders.values() if o.auction_id == auction_id), None)

    async def by_provider_order(self, provider_order_id: str) -> Order | None:
        return next((o for o in self.orders.values()
                     if o.provider_order_id == provider_order_id), None)

    async def invoice(self, order_id: UUID) -> Invoice | None:
        return self.invoices.get(order_id)

    async def save(self, before: Order, after: Order, *,
                   entries: Sequence[LedgerEntry] = (),
                   void_invoice_at: datetime | None = None) -> None:
        current = self.orders.get(before.id)
        if current is None or current.version != before.version:
            raise StaleOrder(str(before.id))
        check_append(after, await self.ledger(after.id), list(entries))
        self.orders[after.id] = after
        for entry in entries:
            self.entries.append(replace(entry, id=len(self.entries) + 1,
                                        created_at=after.updated_at))
        if void_invoice_at and after.id in self.invoices:
            invoice = self.invoices[after.id]
            self.invoices[after.id] = replace(invoice, voided_at=invoice.voided_at
                                              or void_invoice_at)

    async def ledger(self, order_id: UUID) -> list[LedgerEntry]:
        return [entry for entry in self.entries if entry.order_id == order_id]

    async def record_provider_event(self, event: ProviderEvent) -> bool:
        key = (event.provider, event.event_id)
        self.events.setdefault(key, None)
        return self.events[key] is None

    async def mark_event_processed(self, event: ProviderEvent, now: datetime) -> None:
        self.events[(event.provider, event.event_id)] = now

    async def due_capture_retries(self, now: datetime, limit: int) -> list[Order]:
        due = [o for o in self.orders.values() if o.state == "AWAITING_CAPTURE_RETRY"
               and (o.next_capture_at is None or o.next_capture_at <= now)]
        return sorted(due, key=lambda o: o.next_capture_at or o.updated_at)[:limit]

    async def stuck_authorizations(self, authorized_before: datetime,
                                   limit: int) -> list[Order]:
        return [o for o in self.orders.values() if o.state == "AUTHORIZED"
                and o.authorized_at is not None and o.authorized_at <= authorized_before][:limit]

    async def unpaid_past_window(self, now: datetime, limit: int) -> list[Order]:
        return [o for o in self.orders.values() if o.state == "INVOICED"
                and o.payment_due_at is not None and o.payment_due_at <= now][:limit]


def _order(row: Any) -> Order:
    values = dict(row)
    values["currency"] = values["currency"].strip()  # char(3)
    return Order(**values)


def _invoice(row: Any) -> Invoice:
    values = dict(row)
    values["currency"] = values["currency"].strip()
    return Invoice(**values)


def _entry(row: Any) -> LedgerEntry:
    values = dict(row)
    values["currency"] = values["currency"].strip()
    values["entry_type"] = EntryType(values["entry_type"])
    return LedgerEntry(**values)


class PostgresPaymentRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def active_fee(self) -> FeeConfig:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT fee_version, convenience_fee, currency, protection_window_days "
                "FROM fee_config WHERE active"
            )
        if row is None:
            raise RuntimeError("payment.fee_config has no active row")
        return FeeConfig(fee_version=row["fee_version"], convenience_fee=row["convenience_fee"],
                         currency=row["currency"].strip(),
                         protection_window_days=row["protection_window_days"])

    async def _one(self, where: str, *args: Any) -> Order | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_ORDER_COLUMNS} FROM orders WHERE {where}", *args  # noqa: S608
            )
        return None if row is None else _order(row)

    async def create_order(self, order: Order, invoice: Invoice) -> tuple[Order, bool]:
        async with self.pool.acquire() as connection, connection.transaction():
            inserted = await connection.fetchval(
                "INSERT INTO orders (id, auction_id, buyer_id, seller_id, winning_bid_id, "
                "winning_bid_amount, convenience_fee, captured_total, currency, fee_version, "
                "state, saga_id, provider, created_at, updated_at, version, payment_due_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, "
                "$17) ON CONFLICT (auction_id) DO NOTHING RETURNING id",
                order.id, order.auction_id, order.buyer_id, order.seller_id,
                order.winning_bid_id, order.winning_bid_amount, order.convenience_fee,
                order.captured_total, order.currency, order.fee_version, order.state,
                order.saga_id, order.provider, order.created_at, order.updated_at,
                order.version, order.payment_due_at,
            )
            if inserted is not None:
                await connection.execute(
                    f"INSERT INTO invoices ({_INVOICE_COLUMNS}) VALUES "  # noqa: S608
                    "($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
                    invoice.id, invoice.order_id, invoice.invoice_number, invoice.bid_amount,
                    invoice.convenience_fee, invoice.total, invoice.currency,
                    invoice.fee_version, invoice.issued_at, invoice.voided_at,
                )
                return order, True
        existing = await self.by_auction(order.auction_id)
        if existing is None:  # pragma: no cover - the conflicting row cannot vanish
            raise StaleOrder(str(order.auction_id))
        return existing, False

    async def get(self, order_id: UUID) -> Order | None:
        return await self._one("id = $1", order_id)

    async def by_auction(self, auction_id: UUID) -> Order | None:
        return await self._one("auction_id = $1", auction_id)

    async def by_provider_order(self, provider_order_id: str) -> Order | None:
        return await self._one("provider_order_id = $1", provider_order_id)

    async def invoice(self, order_id: UUID) -> Invoice | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_INVOICE_COLUMNS} FROM invoices WHERE order_id = $1",  # noqa: S608
                order_id,
            )
        return None if row is None else _invoice(row)

    async def save(self, before: Order, after: Order, *,
                   entries: Sequence[LedgerEntry] = (),
                   void_invoice_at: datetime | None = None) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            if entries:
                existing = [_entry(row) for row in await connection.fetch(
                    f"SELECT {_LEDGER_COLUMNS} FROM escrow_ledger "  # noqa: S608
                    "WHERE order_id = $1 ORDER BY id", after.id)]
                check_append(after, existing, list(entries))
            status = await connection.execute(
                _UPDATE_ORDER, after.state, after.provider_order_id, after.provider_payment_id,
                after.capture_ref, after.authorized_at, after.capture_attempts,
                after.next_capture_at, after.shipped_at, after.protection_window_ends_at,
                after.version, after.updated_at, before.id, before.version,
            )
            if status != "UPDATE 1":
                raise StaleOrder(str(before.id))
            for entry in entries:
                await connection.execute(
                    _INSERT_LEDGER, entry.order_id, str(entry.entry_type), entry.amount,
                    entry.currency, entry.idempotency_key, entry.saga_id, entry.compensates_id,
                    entry.provider_ref, entry.note,
                )
            if void_invoice_at is not None:
                await connection.execute(
                    "UPDATE invoices SET voided_at = $1 WHERE order_id = $2 AND voided_at IS NULL",
                    void_invoice_at, after.id,
                )

    async def ledger(self, order_id: UUID) -> list[LedgerEntry]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_LEDGER_COLUMNS} FROM escrow_ledger "  # noqa: S608
                "WHERE order_id = $1 ORDER BY id", order_id,
            )
        return [_entry(row) for row in rows]

    async def record_provider_event(self, event: ProviderEvent) -> bool:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "INSERT INTO provider_events (provider, event_id, event_type) VALUES ($1, $2, $3) "
                "ON CONFLICT (provider, event_id) DO UPDATE SET event_type = EXCLUDED.event_type "
                "RETURNING processed_at",
                event.provider, event.event_id, event.event_type,
            )
        return row["processed_at"] is None

    async def mark_event_processed(self, event: ProviderEvent, now: datetime) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE provider_events SET processed_at = $1 "
                "WHERE provider = $2 AND event_id = $3",
                now, event.provider, event.event_id,
            )

    async def due_capture_retries(self, now: datetime, limit: int) -> list[Order]:
        return await self._scan(
            "state = 'AWAITING_CAPTURE_RETRY' AND next_capture_at <= $1 "
            "ORDER BY next_capture_at LIMIT $2", now, limit)

    async def _scan(self, where: str, *args: Any) -> list[Order]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_ORDER_COLUMNS} FROM orders WHERE {where}", *args  # noqa: S608
            )
        return [_order(row) for row in rows]

    async def stuck_authorizations(self, authorized_before: datetime,
                                   limit: int) -> list[Order]:
        return await self._scan(
            "state = 'AUTHORIZED' AND authorized_at <= $1 ORDER BY authorized_at LIMIT $2",
            authorized_before, limit)

    async def unpaid_past_window(self, now: datetime, limit: int) -> list[Order]:
        return await self._scan(
            "state = 'INVOICED' AND payment_due_at <= $1 ORDER BY payment_due_at LIMIT $2",
            now, limit)
