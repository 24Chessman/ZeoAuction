"""CI-sized run of the aggregate load rig (#23).

tests/load/aggregate_rig.py at 100 bids/s over 5 auctions for one second: every auction's
replay must name its live leader, and the per-segment timing of SDD Table 9.3 must be
reported. Real baselines come from the load-test host (docs/perf/week-09-baseline.md).
"""

import importlib.util
import sys
from pathlib import Path
from uuid import UUID

LOAD = Path(__file__).resolve().parents[3] / "tests" / "load"


def load_rig():
    sys.path.insert(0, str(LOAD))
    spec = importlib.util.spec_from_file_location("aggregate_rig", LOAD / "aggregate_rig.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUCTIONS = [UUID(int=0x5EED_0000 + i, version=4) for i in range(5)]


async def test_a_short_aggregate_run_keeps_replay_and_reports_segments():
    rig = load_rig()
    plan = rig.plan_load(23, rate=100, duration=1.0, auctions=AUCTIONS)
    result = await rig.run_inproc(plan, AUCTIONS, replays=10, seed=23)
    assert result["bids"] == 100
    assert result["replay_agrees_all_auctions"]
    assert result["outcomes"]["ACCEPTED"] >= len(AUCTIONS)
    assert set(result["segments_ms"]) == {*rig.SEGMENTS, "other"}
    assert result["intended_latency_ms"]["p95"] >= result["latency_ms"]["p95"] - 0.01
    table = rig.markdown([{"target_rate": 100.0} | result])
    assert "| sequencing_cas | 20 |" in table


def test_the_plan_spreads_over_auctions_and_is_reproducible():
    rig = load_rig()
    plan = rig.plan_load(5, rate=200, duration=0.5, auctions=AUCTIONS, burst=5)
    assert plan == rig.plan_load(5, rate=200, duration=0.5, auctions=AUCTIONS, burst=5)
    assert {p.auction for p in plan} == set(AUCTIONS)
    assert len(plan) == 100
