"""The PostgreSQL repository's statements, against a recording fake of asyncpg."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.auction_repo import PostgresAuctionRepository, StaleAuction
from app.domain.lifecycle import SYSTEM, Actor, transition
from tests.support import NOW, SELLER, draft


class FakePool:
    def __init__(self, status="UPDATE 1", rows=None):
        self.log = []
        self.status = status
        self.rows = rows or []

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        self.log.append("BEGIN")
        try:
            yield
        except BaseException:
            self.log.append("ROLLBACK")
            raise
        self.log.append("COMMIT")

    async def execute(self, sql, *args):
        self.log.append((sql, args))
        return self.status if sql.startswith("UPDATE") else "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        self.log.append((sql, args))
        return self.rows[0] if self.rows else None

    async def fetch(self, sql, *args):
        self.log.append((sql, args))
        return self.rows


def row_of(auction):
    return dict(auction.__dict__)


async def test_add_inserts_the_row_and_a_create_transition():
    pool = FakePool()
    auction = draft()
    await PostgresAuctionRepository(pool).add(auction)
    assert pool.log[0] == "BEGIN"
    assert pool.log[1][0].startswith("INSERT INTO auctions")
    assert len(pool.log[1][1]) == 26
    assert pool.log[2][1][1:5] == ("create", None, "DRAFT", SELLER)
    assert pool.log[-1] == "COMMIT"


async def test_get_round_trips_a_row():
    auction = draft()
    repo = PostgresAuctionRepository(FakePool(rows=[row_of(auction)]))
    assert await repo.get(auction.id) == auction
    assert await PostgresAuctionRepository(FakePool()).get(auction.id) is None


async def test_save_transition_checks_the_version_and_records_the_event():
    pool = FakePool()
    before = draft()
    after = transition(before, "publish", now=NOW, actor=Actor(SELLER))
    await PostgresAuctionRepository(pool).save_transition(before, after, "publish", SELLER)
    sql, args = pool.log[1]
    assert sql.endswith("WHERE id = $14 AND version = $15")
    assert args[-2:] == (before.id, 1)
    assert args[12] == 2  # the new version
    assert pool.log[2][1][1:5] == ("publish", "DRAFT", "SCHEDULED", SELLER)


async def test_a_lost_race_rolls_back():
    pool = FakePool(status="UPDATE 0")
    before = draft()
    after = transition(before, "publish", now=NOW, actor=Actor(SELLER))
    with pytest.raises(StaleAuction):
        await PostgresAuctionRepository(pool).save_transition(before, after, "publish", SELLER)
    assert pool.log[-1] == "ROLLBACK"
    with pytest.raises(StaleAuction):
        await PostgresAuctionRepository(pool).record_bid(before, replace(after, state="DRAFT"))


async def test_record_bid_writes_no_transition_row():
    pool = FakePool()
    before = replace(draft(), state="OPEN")
    await PostgresAuctionRepository(pool).record_bid(before, replace(before, last_bid_seq=1,
                                                                     version=2))
    assert len(pool.log) == 1
    assert pool.log[0][1][6] == 1


async def test_due_filters_rows_through_the_same_rule_as_memory():
    scheduled = replace(draft(), state="SCHEDULED")
    closing = replace(draft(), state="CLOSING", closing_since=NOW)
    still_draining = replace(draft(), state="CLOSING", closing_since=scheduled.opens_at)
    pool = FakePool(rows=[row_of(scheduled), row_of(closing), row_of(still_draining)])
    found = await PostgresAuctionRepository(pool).due(
        scheduled.opens_at, timedelta(seconds=5), limit=10
    )
    assert found == [(scheduled, "open"), (closing, "drained")]
    sql, args = pool.log[0]
    assert "LIMIT $3" in sql
    assert args[1] == scheduled.opens_at - timedelta(seconds=5)


def test_system_actor_is_the_platform():
    assert SYSTEM.is_system and not Actor(SELLER).is_system
