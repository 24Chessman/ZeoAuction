from datetime import timedelta

import pytest

from app.domain.velocity import VelocityTracker
from tests.support import AUCTION, T0

A = str(AUCTION)


def test_rate_is_bids_in_the_window_per_minute():
    tracker = VelocityTracker(60, 5)
    for seq in range(1, 31):
        tracker.record(A, seq, T0 + timedelta(seconds=seq))
    assert tracker.bids_per_minute(A, T0 + timedelta(seconds=31)) == 30.0


def test_a_shorter_window_scales_to_per_minute():
    tracker = VelocityTracker(30, 5)
    for seq in range(1, 11):
        tracker.record(A, seq, T0 + timedelta(seconds=seq))
    assert tracker.bids_per_minute(A, T0 + timedelta(seconds=12)) == 20.0


def test_old_bids_roll_out_of_the_window():
    tracker = VelocityTracker(60, 5)
    for seq in range(1, 11):
        tracker.record(A, seq, T0)
    assert tracker.bids_per_minute(A, T0 + timedelta(seconds=30)) == 10.0
    assert tracker.bids_per_minute(A, T0 + timedelta(seconds=65)) == 0.0


def test_a_replayed_server_seq_is_not_counted_twice():
    tracker = VelocityTracker(60, 5)
    assert tracker.record(A, 1, T0) is not None
    assert tracker.record(A, 1, T0) is None
    assert tracker.record(A, 0, T0) is None
    assert tracker.bids_per_minute(A, T0) == 1.0


def test_buckets_stay_in_time_order_for_late_arrivals():
    tracker = VelocityTracker(60, 5)
    tracker.record(A, 1, T0 + timedelta(seconds=20))
    tracker.record(A, 2, T0)  # higher seq, earlier clock: still counted
    assert tracker.bucket_count(A, T0) == 1
    assert tracker.bids_per_minute(A, T0 + timedelta(seconds=21)) == 2.0


def test_restore_reloads_persisted_buckets_without_double_counting():
    tracker = VelocityTracker(60, 5)
    tracker.record(A, 1, T0)
    tracker.restore(A, T0, 4)
    tracker.restore(A, T0 + timedelta(seconds=5), 2)
    tracker.restore(A, T0 - timedelta(seconds=5), 1)
    assert tracker.bucket_count(A, T0) == 4
    assert tracker.bids_per_minute(A, T0 + timedelta(seconds=6)) == 7.0


def test_unknown_auctions_have_no_velocity():
    tracker = VelocityTracker()
    assert tracker.bids_per_minute("nope", T0) == 0.0
    assert tracker.bucket_count("nope", T0) is None


def test_idle_auctions_are_forgotten():
    tracker = VelocityTracker(60, 5)
    tracker.record(A, 5, T0)
    assert tracker.forget_idle(T0 + timedelta(seconds=10)) == []
    assert tracker.forget_idle(T0 + timedelta(seconds=120)) == [A]
    assert tracker.auctions() == []
    assert tracker.record(A, 1, T0 + timedelta(seconds=130)) is not None  # seq memory reset


@pytest.mark.parametrize(("window", "bucket"), [(60, 0), (5, 10), (60, 7)])
def test_window_must_be_whole_buckets(window, bucket):
    with pytest.raises(ValueError):
        VelocityTracker(window, bucket)
