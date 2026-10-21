"""A failure injected at every saga step leaves no partial settlement (#63, NFR-REL-3).

Each case breaks one step (the database refusing a write, or the provider timing out or
declining), then lets the system do what it does on its own: the client retries, the provider
redelivers, and the settlement worker makes its passes. Afterwards every order must satisfy
:func:`check_no_partial_settlement`, end IN_ESCROW or CANCELLED, and the provider must have
moved the money at most once per operation.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import pytest

from app.adapters.repository import InMemoryPaymentRepository
from app.domain.ledger import LedgerError
from app.domain.saga import check_no_partial_settlement
from app.payment_port.mock_adapter import MockPaymentAdapter
from tests.support import Harness


class DatabaseDown(ConnectionError):
    pass


@dataclass
class Fault:
    method: str  # "create_order" or "save"
    when: Callable[..., bool]
    error: Exception
    times: int = 1


class FaultyRepository(InMemoryPaymentRepository):
    """Raises before a matching write is applied, so the write never happens, the way a
    failed transaction rolls back."""

    def __init__(self) -> None:
        super().__init__()
        self.faults: list[Fault] = []

    def _trip(self, method: str, *args) -> None:
        for fault in self.faults:
            if fault.method == method and fault.times and fault.when(*args):
                fault.times -= 1
                raise fault.error

    async def create_order(self, order, invoice, *, steps=()):
        self._trip("create_order", order)
        return await super().create_order(order, invoice, steps=steps)

    async def save(self, before, after, *, entries=(), void_invoice_at=None, steps=()):
        self._trip("save", before, after)
        await super().save(before, after, entries=entries, void_invoice_at=void_invoice_at,
                           steps=steps)


def moving_to(state: str) -> Callable[..., bool]:
    return lambda before, after: after.state == state and before.state != state


def settle(harness: Harness, passes: int = 6) -> None:
    """Let the worker run, a few minutes apart, as it would in production."""
    for _ in range(passes):
        harness.clock.advance(minutes=3)
        asyncio.run(harness.service.run_due_work())


def assert_consistent(harness: Harness, order_id: UUID, expected: str) -> None:
    order = harness.repo.orders[order_id]
    invoice = asyncio.run(harness.repo.invoice(order_id))
    ledger = asyncio.run(harness.repo.ledger(order_id))
    check_no_partial_settlement(order, invoice, ledger)
    assert order.state == expected, order.state


def provider_moves(port: MockPaymentAdapter, operation: str) -> int:
    """Distinct money movements the provider performed (a replayed key is not a new one)."""
    return len({key for op, key in port.calls if op == operation and key in port._results})


def make(**faults) -> tuple[Harness, FaultyRepository, MockPaymentAdapter]:
    repo, port = FaultyRepository(), MockPaymentAdapter(**faults)
    return Harness(port=port, repo=repo), repo, port


def test_s1_failing_creates_nothing_and_a_retry_settles():
    harness, repo, port = make()
    repo.faults.append(Fault("create_order", lambda _: True, DatabaseDown("db down")))
    assert harness.open().status_code == 500
    assert repo.orders == {} and repo.invoices == {} and harness.events.types() == []
    opened = harness.opened()  # Orchestration's CT-4 client retries
    harness.pay(opened["order_id"])
    assert_consistent(harness, UUID(opened["order_id"]), "IN_ESCROW")


def test_authorisation_failing_to_commit_leaves_the_order_payable():
    harness, repo, port = make()
    opened = harness.opened()
    repo.faults.append(Fault("save", moving_to("AUTHORIZED"), DatabaseDown("db down")))
    assert harness.pay(opened["order_id"]).status_code == 500
    order_id = UUID(opened["order_id"])
    assert_consistent(harness, order_id, "INVOICED")
    assert harness.pay(opened["order_id"]).status_code == 200  # the browser retries
    assert_consistent(harness, order_id, "IN_ESCROW")
    assert provider_moves(port, "capture") == 1


@pytest.mark.parametrize("failures", [1, 4])
def test_s2_timing_out_is_retried_with_the_same_key(failures):
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    port._transient[f"order:{order_id}:capture"] = failures
    harness.pay(opened["order_id"])
    assert_consistent(harness, order_id, "AWAITING_CAPTURE_RETRY")
    settle(harness)
    assert_consistent(harness, order_id, "IN_ESCROW")
    assert provider_moves(port, "capture") == 1


def test_s2_declined_compensates_s1():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    port._declines.add(f"order:{order_id}:capture")
    harness.pay(opened["order_id"])
    assert_consistent(harness, order_id, "CANCELLED")
    assert repo.entries == []


def test_s2_committed_at_the_provider_but_not_in_the_database_is_resumed():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    repo.faults.append(Fault("save", moving_to("CAPTURED"), DatabaseDown("crash after capture")))
    assert harness.pay(opened["order_id"]).status_code == 500
    assert_consistent(harness, order_id, "AUTHORIZED")
    settle(harness)
    assert_consistent(harness, order_id, "IN_ESCROW")
    assert provider_moves(port, "capture") == 1  # the retry replayed the same key


def test_s3_failing_transiently_is_resumed_by_the_worker():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    repo.faults.append(Fault("save", moving_to("IN_ESCROW"), DatabaseDown("crash before hold")))
    assert harness.pay(opened["order_id"]).status_code == 500
    assert_consistent(harness, order_id, "CAPTURED")
    settle(harness)
    assert_consistent(harness, order_id, "IN_ESCROW")
    assert harness.events.types(order_id) == ["INVOICED", "CAPTURED", "HELD"]


def test_s3_failing_definitively_compensates_s2_with_a_full_reversal():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    repo.faults.append(Fault("save", moving_to("IN_ESCROW"), LedgerError("injected")))
    harness.pay(opened["order_id"])
    assert_consistent(harness, order_id, "CANCELLED")
    assert provider_moves(port, "refund") == 1
    assert sum(port.captured.values()) == Decimal("0.00")
    settle(harness)  # nothing further happens to a terminal order
    assert provider_moves(port, "refund") == 1


def test_a_reversal_the_provider_cannot_do_yet_is_retried_with_the_same_key():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    port._transient[f"order:{order_id}:reverse-capture"] = 2
    repo.faults.append(Fault("save", moving_to("IN_ESCROW"), LedgerError("injected"), times=99))
    harness.pay(opened["order_id"])
    assert_consistent(harness, order_id, "CAPTURED")
    settle(harness)
    assert_consistent(harness, order_id, "CANCELLED")
    assert provider_moves(port, "refund") == 1
    assert "payment_saga_compensation_failures_total" in harness.client.get("/metrics").text


def test_a_reversal_the_provider_refuses_leaves_the_money_held_for_an_operator():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    port._declines.add(f"order:{order_id}:reverse-capture")
    repo.faults.append(Fault("save", moving_to("IN_ESCROW"), LedgerError("injected"), times=99))
    harness.pay(opened["order_id"])
    settle(harness, passes=2)
    assert_consistent(harness, order_id, "CAPTURED")  # captured, accounted, never lost
    metrics = harness.client.get("/metrics").text
    assert 'payment_saga_compensation_failures_total{reason="refused",step="S2"}' in metrics


def test_the_compensation_failing_to_commit_after_the_refund_does_not_refund_twice():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    repo.faults.append(Fault("save", moving_to("IN_ESCROW"), LedgerError("injected"), times=99))
    repo.faults.append(Fault("save", moving_to("CANCELLED"), DatabaseDown("crash after refund")))
    assert harness.pay(opened["order_id"]).status_code == 500
    assert_consistent(harness, order_id, "CAPTURED")
    settle(harness)
    assert_consistent(harness, order_id, "CANCELLED")
    assert provider_moves(port, "refund") == 1
    assert port.captured[repo.orders[order_id].capture_ref] == Decimal("0.00")


def test_s1_compensation_failing_is_retried_on_the_next_pass():
    harness, repo, port = make()
    opened = harness.opened()
    order_id = UUID(opened["order_id"])
    repo.faults.append(Fault("save", moving_to("CANCELLED"), DatabaseDown("db down")))
    harness.clock.advance(hours=49)
    assert asyncio.run(harness.service.run_due_work()) == []  # logged, not raised
    assert_consistent(harness, order_id, "INVOICED")
    settle(harness, passes=1)
    assert_consistent(harness, order_id, "CANCELLED")


def test_many_orders_with_random_faults_all_end_consistent():
    """Every injection point at once, across orders: each ends IN_ESCROW or CANCELLED."""
    harness, repo, port = make()
    ids = []
    for index in range(12):
        opened = harness.opened(None)
        order_id = UUID(opened["order_id"])
        ids.append(order_id)
        if index % 4 == 1:
            port._transient[f"order:{order_id}:capture"] = 2
        if index % 4 == 2:
            repo.faults.append(Fault("save", lambda b, a, oid=order_id: a.id == oid
                                     and a.state == "IN_ESCROW", DatabaseDown("crash")))
        if index % 4 == 3:
            repo.faults.append(Fault("save", lambda b, a, oid=order_id: a.id == oid
                                     and a.state == "IN_ESCROW", LedgerError("bad"), times=99))
        harness.pay(opened["order_id"])
    settle(harness)
    states = {}
    for order_id in ids:
        order = repo.orders[order_id]
        check_no_partial_settlement(order, asyncio.run(repo.invoice(order_id)),
                                    asyncio.run(repo.ledger(order_id)))
        states[order.state] = states.get(order.state, 0) + 1
    assert states == {"IN_ESCROW": 9, "CANCELLED": 3}
