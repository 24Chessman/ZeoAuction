"""Time-accelerated fixture proving release occurs within 5 minutes (#25, AC-12).

AC-12: The sweep scans orders(protection_window_ends_at) WHERE state = SHIPPED
and releases expired holds within 5 minutes (300 s). Exposes escrow_sweep_lag_seconds.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.adapters.orders_reader import ExpiredOrder, InMemoryOrdersReader
from app.adapters.payment_client import InMemoryPaymentReleaseClient
from app.sweep import run_once, SWEEP_LAG_SECONDS


def test_time_accelerated_sweep_proves_release_within_5_minutes():
    """Simulate order expiry and time progression in 60s cron intervals."""
    shipped_at = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    protection_ends_at = shipped_at + timedelta(days=7) # Day 7, 10:00:00

    order_id = uuid4()
    reader = InMemoryOrdersReader([
        ExpiredOrder(order_id=order_id, protection_window_ends_at=protection_ends_at)
    ])
    client = InMemoryPaymentReleaseClient()

    # Pass 1: T = Day 7, 09:59:00 (1 min before expiry)
    t1 = protection_ends_at - timedelta(minutes=1)
    released = run_once(reader, client, now=t1)
    assert released == 0
    assert order_id not in client.released

    # Pass 2: T = Day 7, 10:01:00 (1 min after expiry - cron runs every 60s)
    t2 = protection_ends_at + timedelta(minutes=1)
    released = run_once(reader, client, now=t2)
    assert released == 1
    assert order_id in client.released

    # Maximum lag observed on release must be <= 300 s (5 minutes)
    lag = SWEEP_LAG_SECONDS._value.get()
    assert lag <= 300.0
    assert lag == 60.0  # Exactly 60s after expiry


def test_lag_alert_threshold_boundary():
    """When lag exceeds 300s, it records accurately and triggers the lag metric."""
    expiry = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    late_time = expiry + timedelta(seconds=350) # 350s lag

    order_id = uuid4()
    reader = InMemoryOrdersReader([
        ExpiredOrder(order_id=order_id, protection_window_ends_at=expiry)
    ])
    client = InMemoryPaymentReleaseClient()

    released = run_once(reader, client, now=late_time)
    assert released == 1
    assert SWEEP_LAG_SECONDS._value.get() == 350.0
