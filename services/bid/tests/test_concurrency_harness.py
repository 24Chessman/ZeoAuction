"""CI-sized run of the contended single-auction harness (#22, AC-02).

tests/load/concurrency_harness.py at 200 bids/s for one second, twice: both runs must end
with the same winner, and every shuffled replay of each run's accepted log must agree with
the live leader. The full-length run belongs to the load-test host (tests/load/README.md).
"""

import importlib.util
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[3] / "tests" / "load" / "concurrency_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("concurrency_harness", HARNESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_two_runs_at_200_bids_per_second_agree():
    harness = load_harness()
    plan = harness.plan_bids(seed=7, rate=200, duration=1.0)
    first = await harness.run_inproc(plan, replays=25, seed=7)
    second = await harness.run_inproc(plan, replays=25, seed=7)
    assert first.replay_agrees and second.replay_agrees
    assert first.winner == second.winner == harness.expected_winner(plan)
    summary = first.summary()
    assert summary["bids"] == 200
    assert summary["outcomes"]["ACCEPTED"] >= 2


def test_the_schedule_is_reproducible_and_contended():
    harness = load_harness()
    plan = harness.plan_bids(seed=3, rate=200, duration=0.5, burst=10)
    assert plan == harness.plan_bids(seed=3, rate=200, duration=0.5, burst=10)
    assert len({p.at for p in plan}) == 10  # ten bursts of ten simultaneous bids
    top = max(plan, key=lambda p: p.amount)
    assert sum(p.amount == top.amount for p in plan) == 1
