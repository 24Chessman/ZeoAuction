"""Crash recovery: rebuild what Redis lost from ``bid.events`` (ADR-0002).

Kafka is the recovery source, not Redis. Every accepted bid was on ``bid.events`` before its
client was acknowledged, so after Redis loses ``flush:pending`` (or the whole instance) this
replays the retained log and:

1. persists every bid whose ``server_seq`` is above the last persisted one for its auction
   (the batch that never reached PostgreSQL), and
2. restores the hot keys: ``seq:{auction_id}`` is raised to the highest sequence seen, so a
   new bid can never reuse a number, and ``price:{auction_id}`` to the latest leader.

Run on worker start (``REPLAY_ON_START``) or by hand:
``docker compose exec bid-flusher python -m app.replay``.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.store import BidStore, row_from_event

logger = logging.getLogger(__name__)

BID_EVENTS_TOPIC = "bid.events"
SUPPORTED_SCHEMA_VERSIONS = {1}

# Raise a counter, never lower it.
_RAISE_SEQ = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if tonumber(ARGV[1]) > current then
  redis.call('SET', KEYS[1], ARGV[1])
  return 1
end
return 0
"""

# Restore the leader only if it is newer than what Redis holds.
_RESTORE_LEADER = """
local current = tonumber(redis.call('HGET', KEYS[1], 'server_seq') or '0')
if tonumber(ARGV[2]) > current then
  redis.call('HSET', KEYS[1], 'amount', ARGV[1], 'server_seq', ARGV[2],
             'bid_id', ARGV[3], 'bidder_id', ARGV[4])
  return 1
end
return 0
"""


class EventSource(Protocol):
    def events(self) -> AsyncIterator[dict[str, Any]]: ...


@dataclass
class ReplayReport:
    events_read: int = 0
    rows_restored: int = 0
    skipped_unknown_version: int = 0
    auctions: set[UUID] = field(default_factory=set)


async def replay_bid_events(
    source: EventSource, store: BidStore, redis: Any | None = None, *, batch_size: int = 500
) -> ReplayReport:
    report = ReplayReport()
    persisted = await store.max_seq_by_auction()
    latest: dict[UUID, dict[str, Any]] = {}
    batch = []
    async for event in source.events():
        report.events_read += 1
        if event.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            report.skipped_unknown_version += 1  # contracts/README.md rule 4: ignore, don't crash
            continue
        row = row_from_event(event)
        report.auctions.add(row.auction_id)
        if row.auction_id not in latest or row.server_seq > latest[row.auction_id]["server_seq"]:
            latest[row.auction_id] = event
        if row.server_seq > persisted.get(row.auction_id, 0):
            batch.append(row)
        if len(batch) >= batch_size:
            await store.insert_batch(batch)
            report.rows_restored += len(batch)
            batch = []
    if batch:
        await store.insert_batch(batch)
        report.rows_restored += len(batch)
    if redis is not None:
        await restore_hot_keys(redis, latest.values())
    logger.info("Replay read %d events, restored %d rows across %d auctions",
                report.events_read, report.rows_restored, len(report.auctions))
    return report


async def restore_hot_keys(redis: Any, latest_events: Any) -> None:
    raise_seq = redis.register_script(_RAISE_SEQ)
    restore_leader = redis.register_script(_RESTORE_LEADER)
    for event in latest_events:
        auction_id = event["auction_id"]
        await raise_seq(keys=[f"seq:{auction_id}"], args=[event["server_seq"]])
        await restore_leader(
            keys=[f"price:{auction_id}"],
            args=[event["amount"], event["server_seq"], event["bid_id"], event["bidder_id"]],
        )


class KafkaEventSource:
    """Reads every partition of ``bid.events`` from the start of retention to the end offsets
    observed when the replay began, then stops. No consumer group: nothing is committed."""

    def __init__(self, bootstrap_servers: str, topic: str = BID_EVENTS_TOPIC) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic

    async def events(self) -> AsyncIterator[dict[str, Any]]:  # pragma: no cover - needs a broker
        from aiokafka import AIOKafkaConsumer, TopicPartition

        consumer = AIOKafkaConsumer(
            bootstrap_servers=self.bootstrap_servers,
            group_id=None,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            partitions = [TopicPartition(self.topic, p)
                          for p in sorted(await consumer.partitions_for_topic(self.topic) or [])]
            consumer.assign(partitions)
            await consumer.seek_to_beginning(*partitions)
            end = await consumer.end_offsets(partitions)
            remaining = {tp for tp in partitions if end[tp] > await consumer.position(tp)}
            while remaining:
                batches = await consumer.getmany(*remaining, timeout_ms=1000)
                for tp, messages in batches.items():
                    for message in messages:
                        if message.offset < end[tp]:
                            yield json.loads(message.value)
                        if message.offset + 1 >= end[tp]:
                            remaining.discard(tp)
        finally:
            await consumer.stop()


async def _main() -> None:  # pragma: no cover - operational entry point
    from app.settings import Settings
    from app.store import PostgresBidStore
    from zeo_common.db import create_pool
    from zeo_common.redis import create_redis

    settings = Settings.from_env()
    pool = await create_pool(settings.database_url)
    redis = create_redis(settings.redis_url)
    try:
        report = await replay_bid_events(
            KafkaEventSource(settings.kafka_bootstrap_servers), PostgresBidStore(pool), redis
        )
        print(f"events read: {report.events_read}, rows restored: {report.rows_restored}, "
              f"auctions: {len(report.auctions)}")
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
