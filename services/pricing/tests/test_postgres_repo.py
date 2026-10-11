"""The PostgreSQL repository's statements, against a recording fake of asyncpg."""

from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from app.adapters.repository import PostgresPricingRepository, StoredBucket
from app.domain.hot_auction import Change, Transition
from tests.support import AUCTION, T0


class FakePool:
    def __init__(self, rows=None):
        self.log = []
        self.rows = rows or []

    @asynccontextmanager
    async def acquire(self):
        yield self

    async def execute(self, sql, *args):
        self.log.append((sql, args))

    async def executemany(self, sql, args):
        self.log.append((sql, args))

    async def fetch(self, sql, *args):
        self.log.append((sql, args))
        return self.rows


async def test_load_ladder_maps_rows():
    pool = FakePool([{"price_from": Decimal("0.00"), "price_to": None,
                      "base_increment": Decimal("1.00"), "velocity_multiplier": Decimal("2.000")}])
    (rule,) = await PostgresPricingRepository(pool).load_ladder()
    assert (rule.price_to, rule.base_increment) == (None, Decimal("1.00"))
    assert "FROM increment_rules ORDER BY price_from" in pool.log[0][0]


async def test_save_buckets_upserts_keeping_the_larger_count():
    pool = FakePool()
    repo = PostgresPricingRepository(pool)
    await repo.save_buckets([])
    assert pool.log == []
    await repo.save_buckets([StoredBucket(str(AUCTION), T0, 5, 3)])
    sql, rows = pool.log[0]
    assert "ON CONFLICT (auction_id, window_start)" in sql and "GREATEST" in sql
    assert rows == [(AUCTION, T0, 5, 3)]


async def test_recent_buckets_and_prune():
    pool = FakePool([{"auction_id": AUCTION, "window_start": T0, "window_secs": 5,
                      "bid_count": 4}])
    repo = PostgresPricingRepository(pool)
    assert await repo.recent_buckets(T0) == [StoredBucket(str(AUCTION), T0, 5, 4)]
    await repo.prune_buckets(T0)
    assert pool.log[-1] == ("DELETE FROM velocity_windows WHERE window_start < $1", (T0,))


async def test_flag_and_clear_write_the_flag_row():
    pool = FakePool([{"auction_id": AUCTION}])
    repo = PostgresPricingRepository(pool)
    await repo.record_flag(Transition(str(AUCTION), Change.FLAGGED, 31.0, T0, "fast"))
    await repo.record_flag(Transition(str(AUCTION), Change.CLEARED, 9.0, T0, "slow"))
    flag_sql, flag_args = pool.log[0]
    clear_sql, clear_args = pool.log[1]
    assert flag_sql.startswith("INSERT INTO hot_auction_flags") and "cleared_at = NULL" in flag_sql
    assert flag_args == (UUID(str(AUCTION)), T0, "fast")
    assert clear_sql.startswith("UPDATE hot_auction_flags SET cleared_at")
    assert clear_args == (AUCTION, T0)
    assert await repo.active_flags() == [str(AUCTION)]
