import asyncio
import json
from decimal import Decimal
from uuid import uuid4

import fakeredis
import pytest

from app.adapters.price_buffer import (
    FLUSH_PENDING_KEY,
    RedisPriceBuffer,
    price_key,
)
from app.domain.model import Leader
from tests.fakes import AUCTION_ID


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def buffer(redis):
    return RedisPriceBuffer(redis)


def leader(amount: str, seq: int) -> Leader:
    return Leader(Decimal(amount), seq, uuid4(), uuid4())


async def test_no_leader_before_the_first_bid(buffer):
    assert await buffer.leader(AUCTION_ID) is None


async def test_sequence_is_per_auction_and_monotonic(buffer):
    other = uuid4()
    assert [await buffer.next_seq(AUCTION_ID) for _ in range(3)] == [1, 2, 3]
    assert await buffer.next_seq(other) == 1


async def test_first_bid_sets_the_leader_when_none_was_expected(buffer):
    first = leader("100.00", 1)
    assert await buffer.compare_and_set(AUCTION_ID, 0, first) is True
    assert await buffer.leader(AUCTION_ID) == first


async def test_cas_fails_when_the_leader_changed(buffer):
    first, second, late = leader("100.00", 1), leader("110.00", 2), leader("110.00", 3)
    await buffer.compare_and_set(AUCTION_ID, 0, first)
    assert await buffer.compare_and_set(AUCTION_ID, 1, second) is True
    assert await buffer.compare_and_set(AUCTION_ID, 1, late) is False
    assert await buffer.compare_and_set(AUCTION_ID, 0, late) is False
    assert await buffer.leader(AUCTION_ID) == second


async def test_exactly_one_concurrent_cas_against_the_same_leader_wins(buffer):
    await buffer.compare_and_set(AUCTION_ID, 0, leader("100.00", 1))
    contenders = [leader("105.00", seq) for seq in range(2, 22)]
    results = await asyncio.gather(
        *(buffer.compare_and_set(AUCTION_ID, 1, c) for c in contenders)
    )
    assert results.count(True) == 1
    assert await buffer.leader(AUCTION_ID) == contenders[results.index(True)]


async def test_rollback_restores_the_previous_leader(buffer):
    previous, ours = leader("100.00", 1), leader("105.00", 2)
    await buffer.compare_and_set(AUCTION_ID, 0, previous)
    await buffer.compare_and_set(AUCTION_ID, 1, ours)
    assert await buffer.rollback(AUCTION_ID, ours, previous) is True
    assert await buffer.leader(AUCTION_ID) == previous


async def test_rollback_of_the_first_bid_clears_the_price(buffer, redis):
    ours = leader("100.00", 1)
    await buffer.compare_and_set(AUCTION_ID, 0, ours)
    assert await buffer.rollback(AUCTION_ID, ours, None) is True
    assert await redis.exists(price_key(AUCTION_ID)) == 0


async def test_rollback_never_undoes_someone_else_outbidding_us(buffer):
    ours, theirs = leader("100.00", 1), leader("105.00", 2)
    await buffer.compare_and_set(AUCTION_ID, 0, ours)
    await buffer.compare_and_set(AUCTION_ID, 1, theirs)
    assert await buffer.rollback(AUCTION_ID, ours, None) is False
    assert await buffer.leader(AUCTION_ID) == theirs


async def test_accepted_events_are_queued_in_order_for_the_flusher(buffer, redis):
    for seq in (1, 2, 3):
        await buffer.enqueue_for_flush({"auction_id": str(AUCTION_ID), "server_seq": seq})
    assert await buffer.pending_depth() == 3
    queued = [json.loads(raw) for raw in await redis.lrange(FLUSH_PENDING_KEY, 0, -1)]
    assert [q["event"]["server_seq"] for q in queued] == [1, 2, 3]
    assert all(q["enqueued_at_ms"] > 0 for q in queued)
