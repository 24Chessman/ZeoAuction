"""Batched persistence of accepted bids (#30, ADR-0002, SDD 4.4).

The bid service appends every broker-acknowledged ``BidAccepted v1`` event to the Redis
list ``flush:pending`` (``{"event": ..., "enqueued_at_ms": ...}``). This worker drains it
into ``bid.bids`` in batches bounded by **size** (``max_size`` rows) and **age** (the oldest
waiting bid is never older than ``max_age_seconds`` before it is written).

At-least-once: a batch is read without being removed, written in one transaction, and only
then trimmed from the list. A crash between the two re-writes the batch on restart, which
the idempotent insert absorbs. Exactly one flusher instance runs (Render worker), so the
head of the list is only ever trimmed by us.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from app.store import BidStore, row_from_event

logger = logging.getLogger(__name__)

FLUSH_PENDING_KEY = "flush:pending"
DEAD_LETTER_KEY = "flush:dead"


@dataclass(frozen=True)
class BatchPolicy:
    max_size: int = 500
    max_age_seconds: float = 0.5

    def due(self, pending: int, oldest_age_seconds: float) -> bool:
        return pending >= self.max_size or oldest_age_seconds >= self.max_age_seconds


class FlusherMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.rows = Counter("bid_flush_rows", "Bids written to PostgreSQL.", registry=registry)
        self.batch_size = Histogram(
            "bid_flush_batch_size", "Rows per flushed batch.",
            buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000), registry=registry,
        )
        self.pending = Gauge(
            "bid_flush_pending", "Accepted bids waiting in flush:pending.", registry=registry
        )
        self.dead = Counter(
            "bid_flush_dead_letters", "Unparseable records moved to flush:dead.", registry=registry
        )
        self.replayed = Counter(
            "bid_replay_rows", "Bids restored from bid.events by replay.", registry=registry
        )


class BatchFlusher:
    def __init__(
        self,
        redis: Any,
        store: BidStore,
        policy: BatchPolicy,
        metrics: FlusherMetrics,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.redis = redis
        self.store = store
        self.policy = policy
        self.metrics = metrics
        self.clock = clock

    async def flush_once(self, *, force: bool = False) -> int:
        """Write one batch if it is due (or ``force``). Returns the number of rows written."""
        raw = await self.redis.lrange(FLUSH_PENDING_KEY, 0, self.policy.max_size - 1)
        self.metrics.pending.set(await self.redis.llen(FLUSH_PENDING_KEY))
        if not raw:
            return 0
        records, rows, dead = [], [], []
        for item in raw:
            try:
                record = json.loads(item)
                rows.append(row_from_event(record["event"]))
                records.append(record)
            except (ValueError, KeyError, TypeError):
                dead.append(item)
        oldest_age = self.clock() - records[0]["enqueued_at_ms"] / 1000 if records else 0.0
        if records and not force and not self.policy.due(len(raw), oldest_age):
            return 0
        if rows:
            await self.store.insert_batch(rows)
        for item in dead:
            logger.error("Unparseable flush record moved to %s", DEAD_LETTER_KEY)
            await self.redis.rpush(DEAD_LETTER_KEY, item)
            self.metrics.dead.inc()
        await self.redis.ltrim(FLUSH_PENDING_KEY, len(raw), -1)
        self.metrics.rows.inc(len(rows))
        if rows:
            self.metrics.batch_size.observe(len(rows))
        return len(rows)

    async def run(self, stop: asyncio.Event, poll_seconds: float = 0.05) -> None:
        """Flush until ``stop`` is set; a failing database is retried, never skipped."""
        while not stop.is_set():
            try:
                written = await self.flush_once()
            except Exception:
                logger.exception("Flush failed; the batch stays queued and is retried")
                written = 0
                await asyncio.sleep(1.0)
            if written == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass
        await self.drain()

    async def drain(self) -> None:
        """Write everything still queued, regardless of the policy (graceful shutdown)."""
        while await self.flush_once(force=True):
            pass
