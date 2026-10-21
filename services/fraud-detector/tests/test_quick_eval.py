"""The v1 measurement end to end: dataset -> consumer -> scorer -> alerts -> recall/precision."""

from decimal import Decimal

from eval.quick_eval import evaluate, load, score

from dataset.generator import DatasetConfig, generate


def small(seed: int):
    dataset = generate(DatasetConfig(seed=seed, n_auctions=80, n_rings=25,
                                     n_honest_accounts=300, n_clean_sellers=20,
                                     min_clean_auctions=20))
    labels = {(str(lb.auction_id), str(lb.bidder_id)): lb.signals for lb in dataset.labels}
    return dataset.events, labels


async def test_v1_finds_most_rings_before_close_on_a_held_out_dataset():
    events, labels = small(seed=11)
    result = await evaluate(events, labels, dataset_version="small")
    assert result.events == len(events)
    assert result.late_alerts == 0
    assert result.median_lead_hours > 0
    assert result.recall >= 0.8 and result.precision >= 0.75
    assert result.auction_recall >= 0.9
    assert set(result.recall_by_signal) <= {"seller_linked", "shared_fingerprint",
                                            "high_velocity", "regular_interarrival"}
    run = result.as_run()
    assert run.detector_version == "shill-v1" and run.threshold == Decimal("0.6000")


async def test_a_stricter_threshold_trades_recall_for_precision():
    events, labels = small(seed=12)
    loose = await evaluate(events, labels, threshold=0.5)
    strict = await evaluate(events, labels, threshold=0.8)
    assert loose.recall >= strict.recall
    assert strict.precision >= loose.precision


def test_scoring_counts_only_named_suspects():
    labels = {("a1", "shill"): "seller_linked", ("a2", "shill2"): "high_velocity"}
    alerts = [{"auction_id": "a1", "suspect_bidder_ids": ["shill", "honest"],
               "raised_at": "2026-10-05T10:00:00Z", "auction_closes_at": "2026-10-05T12:00:00Z"}]
    result = score(alerts, labels, threshold=0.6, events=10, late=1, dataset_version="t")
    assert (result.recall, result.precision) == (0.5, 0.5)
    assert result.auction_recall == 0.5 and result.auction_precision == 1.0
    assert result.median_lead_hours == 2.0
    assert result.recall_by_signal == {"high_velocity": 0.0, "seller_linked": 1.0}
    assert not result.meets_target()
    empty = score([], {}, threshold=0.6, events=0, late=0, dataset_version="t")
    assert (empty.recall, empty.precision, empty.median_lead_hours) == (0.0, 0.0, None)


async def test_dataset_v1_meets_the_target():
    events, labels, version = load(None)
    result = await evaluate(events, labels, dataset_version=version)
    assert version == "v1"
    assert result.meets_target(), result
