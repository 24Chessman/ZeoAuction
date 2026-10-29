"""``ShillAlert v1`` publishing to ``fraud.alerts`` (#53; contract
contracts/events/shill_alert.v1.json, SDD 5.4.1).

An alert is only worth anything before its auction closes (FR-FRAUD-4, AC-14), so
:func:`must_precede_close` asserts ``raised_at < auction_closes_at`` before anything is sent. A
late alert is **not published** (the contract forbids it, and nobody can act on it), but it is
stored in ``fraud.fraud_alerts``, where the generated ``raised_before_close`` column records it
as a miss, and counted in ``fraud_alerts_total{outcome="late"}``.

The ``alert_id`` is derived from the auction and the bidder that tipped it, so re-scoring the
same events after a restart (at-least-once delivery) produces the same alert id: the table
insert is a no-op and consumers of ``fraud.alerts`` deduplicate by it.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from prometheus_client import CollectorRegistry, Counter

from app.scorer import AlertDecision

logger = logging.getLogger(__name__)

FRAUD_ALERTS_TOPIC = "fraud.alerts"
SCHEMA_VERSION = 1
_ALERT_NAMESPACE = uuid.UUID("5f1d7a52-3c41-4f0e-9d6b-6a1e0f3b7c21")


class LateAlertError(Exception):
    """The alert would be raised at or after the auction's close: a miss, not a hit."""


class AlertOutcome(Enum):
    PUBLISHED = "published"
    LATE = "late"
    NO_CLOSE = "no_close"  # the bid didn't say when the auction closes, so it can't be checked


def must_precede_close(raised_at: datetime, auction_closes_at: datetime) -> None:
    """``AlertPublisher.mustPrecedeClose`` of SDD 5.4.1."""
    if raised_at >= auction_closes_at:
        raise LateAlertError(
            f"alert raised at {iso_utc(raised_at)}, auction closed at {iso_utc(auction_closes_at)}")


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def alert_id_for(auction_id: str, bidder_id: str) -> uuid.UUID:
    return uuid.uuid5(_ALERT_NAMESPACE, f"{auction_id}:{bidder_id}")


def build_shill_alert(
    decision: AlertDecision,
    raised_at: datetime,
    *,
    ring_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    if decision.auction_closes_at is None:
        raise ValueError("an alert needs the auction's close time")
    trigger = decision.trigger.features
    return {
        "alert_id": str(alert_id_for(decision.auction_id, trigger.bidder_id)),
        "schema_version": SCHEMA_VERSION,
        "auction_id": decision.auction_id,
        "ring_id": str(ring_id) if ring_id is not None else None,
        "score": decision.score,
        "signals": decision.trigger.signals.evidence(),
        "suspect_bidder_ids": list(decision.suspects),
        "raised_at": iso_utc(raised_at),
        "auction_closes_at": iso_utc(decision.auction_closes_at),
    }


class AlertProducer(Protocol):
    async def publish(self, alert: dict[str, Any]) -> None: ...


class AlertRepository(Protocol):
    async def save_alert(self, alert: dict[str, Any]) -> bool: ...


class AlertMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.alerts = Counter("fraud_alerts_total", "Shill alerts by outcome.", ["outcome"],
                              registry=registry)


class AlertPublisher:
    def __init__(self, producer: AlertProducer, repository: AlertRepository, *,
                 metrics: AlertMetrics | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.producer = producer
        self.repository = repository
        self.metrics = metrics or AlertMetrics(CollectorRegistry())
        self.clock = clock

    async def publish(self, decision: AlertDecision,
                      raised_at: datetime | None = None,
                      *,
                      ring_id: str | uuid.UUID | None = None) -> AlertOutcome:
        """Store the alert, and publish it if it precedes the close. ``raised_at`` defaults to
        now; a replay of history passes the bid's own time instead."""
        if decision.auction_closes_at is None:
            self.metrics.alerts.labels(outcome=AlertOutcome.NO_CLOSE.value).inc()
            logger.warning("No close time on %s; alert dropped", decision.auction_id)
            return AlertOutcome.NO_CLOSE
        raised_at = raised_at or self.clock()
        alert = build_shill_alert(decision, raised_at, ring_id=ring_id)
        try:
            must_precede_close(raised_at, decision.auction_closes_at)
        except LateAlertError as late:
            await self.repository.save_alert(alert)
            self.metrics.alerts.labels(outcome=AlertOutcome.LATE.value).inc()
            logger.warning("Late shill alert for %s, recorded as a miss: %s",
                           decision.auction_id, late)
            return AlertOutcome.LATE
        await self.repository.save_alert(alert)
        await self.producer.publish(alert)
        self.metrics.alerts.labels(outcome=AlertOutcome.PUBLISHED.value).inc()
        logger.info("Shill alert %s on %s (score %s, %d suspects)", alert["alert_id"],
                    decision.auction_id, decision.score, len(decision.suspects))
        return AlertOutcome.PUBLISHED
