import pytest

from app.domain.hot_auction import Change, HotAuctions, HotPolicy
from tests.support import T0


def test_crossing_the_entry_threshold_flags_the_auction():
    hot = HotAuctions(HotPolicy(30, 15))
    assert hot.evaluate("a", 29.9, T0) is None
    transition = hot.evaluate("a", 30.0, T0)
    assert transition.change is Change.FLAGGED
    assert "30.0 bids/min >= 30" in transition.reason
    assert hot.is_hot("a") and hot.count() == 1


def test_hysteresis_keeps_the_flag_between_the_thresholds():
    hot = HotAuctions(HotPolicy(30, 15))
    hot.evaluate("a", 40, T0)
    assert hot.evaluate("a", 20, T0) is None
    assert hot.evaluate("a", 15, T0) is None
    assert hot.is_hot("a")
    cleared = hot.evaluate("a", 14.9, T0)
    assert cleared.change is Change.CLEARED
    assert not hot.is_hot("a")
    assert hot.evaluate("a", 20, T0) is None  # below entry again: stays cold


def test_restore_marks_auctions_hot():
    hot = HotAuctions(HotPolicy())
    hot.restore(["a", "b"])
    assert hot.is_hot("b") and hot.count() == 2


@pytest.mark.parametrize(("enter", "exit_"), [(10, 20), (10, 0)])
def test_invalid_policies_are_refused(enter, exit_):
    with pytest.raises(ValueError):
        HotPolicy(enter, exit_)
