"""Tests for escrow sweep run_once (#25, Plan 6)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.adapters.orders_reader import ExpiredOrder, InMemoryOrdersReader
from app.adapters.payment_client import InMemoryPaymentReleaseClient
from app.sweep import run_once, main, SWEEP_LAG_SECONDS


def test_sweep_releases_expired_orders():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    order1 = uuid4()
    order2 = uuid4()
    future_order = uuid4()

    reader = InMemoryOrdersReader([
        ExpiredOrder(order_id=order1, protection_window_ends_at=now - timedelta(minutes=2)),
        ExpiredOrder(order_id=order2, protection_window_ends_at=now - timedelta(seconds=30)),
        ExpiredOrder(order_id=future_order, protection_window_ends_at=now + timedelta(days=2)),
    ])
    client = InMemoryPaymentReleaseClient()

    released = run_once(reader, client, now=now)
    assert released == 2
    assert order1 in client.released
    assert order2 in client.released
    assert future_order not in client.released


def test_sweep_is_idempotent():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    order1 = uuid4()

    reader = InMemoryOrdersReader([
        ExpiredOrder(order_id=order1, protection_window_ends_at=now - timedelta(minutes=1)),
    ])
    client = InMemoryPaymentReleaseClient()

    assert run_once(reader, client, now=now) == 1
    # Second run with same reader & client
    assert run_once(reader, client, now=now) == 1


def test_main_runs_and_logs(capsys):
    main()
    captured = capsys.readouterr().out
    assert "escrow sweep finished" in captured
