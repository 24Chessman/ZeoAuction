"""Alert and evaluation-run persistence in the ``fraud`` schema (infra/postgres/init/75-fraud.sql).

``fraud.fraud_alerts`` keeps every alert, late ones included: its generated
``raised_before_close`` column is what makes a late alert a recorded miss (AC-14). The insert
is idempotent on ``alert_id``, which is derived from (auction, bidder), so re-scoring after a
restart stores nothing twice. ``fraud.evaluation_runs`` records each scored replay of the
labelled dataset (ADR-0008).
"""

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

_INSERT_ALERT = (
    "INSERT INTO fraud.fraud_alerts (alert_id, auction_id, ring_id, score, signals, raised_at, "
    "auction_closes_at) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7) "
    "ON CONFLICT (alert_id) DO NOTHING"
)
_INSERT_RUN = (
    "INSERT INTO fraud.evaluation_runs (dataset_version, detector_version, threshold, recall, "
    "precision, late_alerts) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id"
)


@dataclass(frozen=True)
class EvaluationRun:
    dataset_version: str
    detector_version: str
    threshold: Decimal
    recall: Decimal
    precision: Decimal
    late_alerts: int


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ratio(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


class PostgresAlertRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def save_alert(self, alert: dict[str, Any]) -> bool:
        """True if stored, False if this alert id was already there."""
        async with self.pool.acquire() as connection:
            status = await connection.execute(
                _INSERT_ALERT,
                alert["alert_id"],
                alert["auction_id"],
                alert.get("ring_id"),
                _ratio(alert["score"]),
                json.dumps(alert["signals"], sort_keys=True),
                _time(alert["raised_at"]),
                _time(alert["auction_closes_at"]),
            )
        return status.endswith(" 1")

    async def record_evaluation(self, run: EvaluationRun) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval(
                _INSERT_RUN, run.dataset_version, run.detector_version, run.threshold,
                run.recall, run.precision, run.late_alerts)


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[str, dict[str, Any]] = {}
        self.runs: list[EvaluationRun] = []

    async def save_alert(self, alert: dict[str, Any]) -> bool:
        if alert["alert_id"] in self.alerts:
            return False
        self.alerts[alert["alert_id"]] = alert
        return True

    async def record_evaluation(self, run: EvaluationRun) -> int:
        self.runs.append(run)
        return len(self.runs)

    def misses(self) -> list[dict[str, Any]]:
        """Alerts raised at or after close (``raised_before_close`` false in the table)."""
        return [a for a in self.alerts.values()
                if _time(a["raised_at"]) >= _time(a["auction_closes_at"])]
