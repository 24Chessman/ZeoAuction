"""Durable side of the Pricing Engine: the ladder, velocity buckets and hot flags.

None of it is on the CT-3 hot path: the ladder is read once at start-up, buckets are flushed in
the background, and flags are written only when an auction changes state. The service connects
as ``pricing_svc``, whose ``search_path`` is the ``pricing`` schema.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.hot_auction import Change, Transition
from app.domain.increment import DEFAULT_LADDER, IncrementRule


@dataclass(frozen=True)
class StoredBucket:
    auction_id: str
    start: datetime
    seconds: int
    count: int


class PricingRepository(Protocol):
    async def load_ladder(self) -> tuple[IncrementRule, ...]: ...

    async def save_buckets(self, buckets: list[StoredBucket]) -> None: ...

    async def recent_buckets(self, since: datetime) -> list[StoredBucket]: ...

    async def prune_buckets(self, before: datetime) -> None: ...

    async def record_flag(self, transition: Transition) -> None: ...

    async def active_flags(self) -> list[str]: ...


class InMemoryPricingRepository:
    def __init__(self, ladder: tuple[IncrementRule, ...] = DEFAULT_LADDER) -> None:
        self.ladder = ladder
        self.buckets: dict[tuple[str, datetime], StoredBucket] = {}
        self.flags: dict[str, Transition] = {}

    async def load_ladder(self) -> tuple[IncrementRule, ...]:
        return self.ladder

    async def save_buckets(self, buckets: list[StoredBucket]) -> None:
        for bucket in buckets:
            self.buckets[(bucket.auction_id, bucket.start)] = bucket

    async def recent_buckets(self, since: datetime) -> list[StoredBucket]:
        return [b for b in self.buckets.values() if b.start >= since]

    async def prune_buckets(self, before: datetime) -> None:
        for key in [k for k, b in self.buckets.items() if b.start < before]:
            del self.buckets[key]

    async def record_flag(self, transition: Transition) -> None:
        self.flags[transition.auction_id] = transition

    async def active_flags(self) -> list[str]:
        return [a for a, t in self.flags.items() if t.change is Change.FLAGGED]


class PostgresPricingRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def load_ladder(self) -> tuple[IncrementRule, ...]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT price_from, price_to, base_increment, velocity_multiplier "
                "FROM increment_rules ORDER BY price_from"
            )
        return tuple(IncrementRule(r["price_from"], r["price_to"], r["base_increment"],
                                   r["velocity_multiplier"]) for r in rows)

    async def save_buckets(self, buckets: list[StoredBucket]) -> None:
        if not buckets:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO velocity_windows (auction_id, window_start, window_secs, bid_count) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (auction_id, window_start) "
                "DO UPDATE SET bid_count = GREATEST(velocity_windows.bid_count, "
                "EXCLUDED.bid_count)",
                [(UUID(b.auction_id), b.start, b.seconds, b.count) for b in buckets],
            )

    async def recent_buckets(self, since: datetime) -> list[StoredBucket]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT auction_id, window_start, window_secs, bid_count "
                "FROM velocity_windows WHERE window_start >= $1",
                since,
            )
        return [StoredBucket(str(r["auction_id"]), r["window_start"], r["window_secs"],
                             r["bid_count"]) for r in rows]

    async def prune_buckets(self, before: datetime) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM velocity_windows WHERE window_start < $1", before)

    async def record_flag(self, transition: Transition) -> None:
        async with self.pool.acquire() as conn:
            if transition.change is Change.FLAGGED:
                await conn.execute(
                    "INSERT INTO hot_auction_flags (auction_id, flagged_at, reason, cleared_at) "
                    "VALUES ($1, $2, $3, NULL) ON CONFLICT (auction_id) DO UPDATE SET "
                    "flagged_at = EXCLUDED.flagged_at, reason = EXCLUDED.reason, "
                    "cleared_at = NULL",
                    UUID(transition.auction_id), transition.at, transition.reason,
                )
            else:
                await conn.execute(
                    "UPDATE hot_auction_flags SET cleared_at = $2 "
                    "WHERE auction_id = $1 AND cleared_at IS NULL",
                    UUID(transition.auction_id), transition.at,
                )

    async def active_flags(self) -> list[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT auction_id FROM hot_auction_flags WHERE cleared_at IS NULL")
        return [str(r["auction_id"]) for r in rows]
