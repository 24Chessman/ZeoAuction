"""v1 recall and precision of the shill detector on the labelled dataset (#53, SDD 5.4.3).

Replays the dataset through the same path live traffic takes: each event is encoded as the
``bid.events`` message, handed to :meth:`FraudConsumer.handle`, scored by the
:class:`ScoringPipeline` and published by the :class:`AlertPublisher` (into memory). Time is
the replay's: the windows expire and alerts are raised at the bids' own timestamps, so "before
close" (AC-14) is judged as it would have been live, and a late alert counts as a miss.

A labelled (auction, shill account) pair is **detected** when an alert raised before that
auction's close names the account as a suspect. Precision is over every pair named that way.

    python -m eval.quick_eval                        # dataset v1 from tests/fixtures/fraud
    python -m eval.quick_eval --seed 7               # a freshly generated held-out dataset
    python -m eval.quick_eval --sweep                # the recall-precision curve (FR-DOC-6)
    python -m eval.quick_eval --record "$DATABASE_URL"   # also insert into fraud.evaluation_runs

This is the honest first number (Plan 5). The formal harness with the per-signal breakdown
and the published curve is #57 (Plan 7).
"""

import argparse
import asyncio
import csv
import json
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.adapters.alert_producer import InMemoryAlertProducer
from app.adapters.alert_repo import EvaluationRun, InMemoryAlertRepository
from app.alerts import AlertPublisher
from app.consumer import FraudConsumer
from app.features import FeatureExtractor
from app.pipeline import ScoringPipeline
from app.scorer import DETECTOR_VERSION, V1_THRESHOLD, ShillDetector, ShillScorer
from app.windows import AuctionWindows

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fraud"
Pair = tuple[str, str]


@dataclass
class Result:
    dataset_version: str
    detector_version: str
    threshold: float
    events: int
    labelled_pairs: int
    flagged_pairs: int
    true_positives: int
    recall: float
    precision: float
    auction_recall: float
    auction_precision: float
    alerts: int
    late_alerts: int
    median_lead_hours: float | None  # how long before close the first alert came
    recall_by_signal: dict[str, float] = field(default_factory=dict)

    def meets_target(self) -> bool:
        """NFR-FRAUD-1: recall >= 0.90 at precision >= 0.75."""
        return self.recall >= 0.90 and self.precision >= 0.75

    def as_run(self) -> EvaluationRun:
        def ratio(value: float) -> Decimal:
            return Decimal(str(value)).quantize(Decimal("0.0001"))

        return EvaluationRun(self.dataset_version, self.detector_version, ratio(self.threshold),
                             ratio(self.recall), ratio(self.precision), self.late_alerts)


class ReplayClock:
    """The replay's "now": the time of the last bid handed to the consumer."""

    def __init__(self) -> None:
        self.now = datetime(1970, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_labels(path: Path) -> dict[Pair, str]:
    with path.open(newline="", encoding="utf-8") as rows:
        return {(r["auction_id"], r["bidder_id"]): r["signals"] for r in csv.DictReader(rows)}


async def evaluate(events: Iterable[dict[str, Any]], labels: dict[Pair, str], *,
                   threshold: float = V1_THRESHOLD, dataset_version: str = "v1") -> Result:
    clock = ReplayClock()
    producer, repository = InMemoryAlertProducer(), InMemoryAlertRepository()
    pipeline = ScoringPipeline(ShillDetector(ShillScorer(threshold=threshold)),
                               AlertPublisher(producer, repository, clock=clock),
                               replay_time=True)
    consumer = FraudConsumer(None, windows=AuctionWindows(), extractor=FeatureExtractor(),
                             on_features=pipeline, on_expire=pipeline.forget_auction,
                             clock=clock)
    count = 0
    for event in events:
        clock.now = max(clock.now, _time(event["accepted_at"]))
        await consumer.handle(json.dumps(event).encode("utf-8"))
        count += 1
    return score(producer.alerts, labels, threshold=threshold, events=count,
                 late=len(repository.misses()), dataset_version=dataset_version)


def score(alerts: list[dict[str, Any]], labels: dict[Pair, str], *, threshold: float,
          events: int, late: int, dataset_version: str) -> Result:
    flagged: set[Pair] = set()
    first_alert: dict[str, dict[str, Any]] = {}
    for alert in alerts:  # only alerts that preceded the close were published
        flagged.update((alert["auction_id"], bidder) for bidder in alert["suspect_bidder_ids"])
        first_alert.setdefault(alert["auction_id"], alert)
    labelled = set(labels)
    hits = flagged & labelled
    shilled = {auction for auction, _ in labelled}
    alerted = set(first_alert)
    leads = [(_time(a["auction_closes_at"]) - _time(a["raised_at"])).total_seconds() / 3600
             for a in first_alert.values()]
    by_signal: dict[str, list[bool]] = defaultdict(list)
    for pair, signals in labels.items():
        for signal in signals.split("|"):
            by_signal[signal].append(pair in hits)
    return Result(
        dataset_version=dataset_version,
        detector_version=DETECTOR_VERSION,
        threshold=threshold,
        events=events,
        labelled_pairs=len(labelled),
        flagged_pairs=len(flagged),
        true_positives=len(hits),
        recall=_round(len(hits) / len(labelled)) if labelled else 0.0,
        precision=_round(len(hits) / len(flagged)) if flagged else 0.0,
        auction_recall=_round(len(alerted & shilled) / len(shilled)) if shilled else 0.0,
        auction_precision=_round(len(alerted & shilled) / len(alerted)) if alerted else 0.0,
        alerts=len(alerts),
        late_alerts=late,
        median_lead_hours=round(statistics.median(leads), 2) if leads else None,
        recall_by_signal={s: _round(sum(v) / len(v)) for s, v in sorted(by_signal.items())},
    )


def _round(value: float) -> float:
    return round(value, 4)


def load(seed: int | None) -> tuple[list[dict[str, Any]], dict[Pair, str], str]:
    if seed is None:
        from dataset.replay import read_events

        return (list(read_events(FIXTURES / "dataset-v1.jsonl.gz")),
                read_labels(FIXTURES / "labels-v1.csv"), "v1")
    from dataset.generator import DatasetConfig, generate

    dataset = generate(DatasetConfig(seed=seed))
    labels = {(str(lb.auction_id), str(lb.bidder_id)): lb.signals for lb in dataset.labels}
    return dataset.events, labels, f"v1-seed{seed}"


async def record(database_url: str, result: Result) -> int:  # pragma: no cover - needs Postgres
    from app.adapters.alert_repo import PostgresAlertRepository
    from zeo_common.db import create_pool

    pool = await create_pool(database_url, max_size=1)
    try:
        return await PostgresAlertRepository(pool).record_evaluation(result.as_run())
    finally:
        await pool.close()


async def _main(args: argparse.Namespace) -> None:
    events, labels, version = load(args.seed)
    if args.sweep:
        thresholds = [round(t / 20, 2) for t in range(8, 18)]
        curve = [await evaluate(events, labels, threshold=t, dataset_version=version)
                 for t in thresholds]
        print(json.dumps([{k: getattr(r, k) for k in ("threshold", "recall", "precision",
                                                     "late_alerts")} for r in curve], indent=2))
        return
    result = await evaluate(events, labels, threshold=args.threshold, dataset_version=version)
    print(json.dumps(asdict(result) | {"meets_target": result.meets_target()}, indent=2))
    if args.record:
        print(f"evaluation_runs id {await record(args.record, result)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, help="generate a held-out dataset with this seed")
    parser.add_argument("--threshold", type=float, default=V1_THRESHOLD)
    parser.add_argument("--sweep", action="store_true", help="print the recall-precision curve")
    parser.add_argument("--record", metavar="DATABASE_URL",
                        help="insert the result into fraud.evaluation_runs")
    asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
