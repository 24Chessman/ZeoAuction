import asyncio

import fakeredis
import pytest

from app.domain.idempotency import (
    IdempotencyConflict,
    IdempotencyGuard,
    StoredOutcome,
    redis_key,
)

KEY = "c0ffee00-bid-0001"
ALICE = "00000000-0000-4000-8000-000000000004"
BOB = "00000000-0000-4000-8000-000000000005"


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def guard(redis):
    return IdempotencyGuard(redis)


async def test_first_request_claims_the_key_with_a_24h_ttl(guard, redis):
    assert await guard.claim(KEY, ALICE) is None
    ttl = await redis.ttl(redis_key(KEY))
    assert 24 * 3600 - 5 <= ttl <= 24 * 3600


async def test_retry_after_completion_returns_the_original_outcome(guard):
    await guard.claim(KEY, ALICE)
    await guard.complete(KEY, ALICE, 202, {"bid_id": "b1", "server_seq": 7})
    assert await guard.claim(KEY, ALICE) == StoredOutcome(202, {"bid_id": "b1", "server_seq": 7})


async def test_a_stored_rejection_is_replayed_too(guard):
    await guard.claim(KEY, ALICE)
    body = {"code": "BID_BELOW_INCREMENT", "message": "Minimum next bid is 5.00",
            "details": {"min_next_bid": "5.00"}}
    await guard.complete(KEY, ALICE, 422, body)
    assert await guard.claim(KEY, ALICE) == StoredOutcome(422, body)


async def test_concurrent_duplicate_is_refused_while_in_flight(guard):
    await guard.claim(KEY, ALICE)
    with pytest.raises(IdempotencyConflict, match="in progress"):
        await guard.claim(KEY, ALICE)


async def test_exactly_one_of_many_simultaneous_requests_claims(guard):
    async def attempt():
        try:
            return await guard.claim(KEY, ALICE)
        except IdempotencyConflict:
            return "refused"

    results = await asyncio.gather(*(attempt() for _ in range(50)))
    assert results.count(None) == 1
    assert results.count("refused") == 49


async def test_another_user_cannot_see_or_reuse_the_outcome(guard):
    await guard.claim(KEY, ALICE)
    await guard.complete(KEY, ALICE, 202, {"bid_id": "secret"})
    with pytest.raises(IdempotencyConflict, match="another request"):
        await guard.claim(KEY, BOB)


async def test_release_lets_a_retry_run_again(guard):
    await guard.claim(KEY, ALICE)
    await guard.release(KEY)
    assert await guard.claim(KEY, ALICE) is None


class ExpiringStore:
    """SET NX fails, then the key expires before GET: the guard must claim on the retry."""

    def __init__(self):
        self.sets = 0

    async def set(self, name, value, ex=None, nx=False):
        self.sets += 1
        return self.sets > 1

    async def get(self, name):
        return None

    async def delete(self, *names):
        return 0


async def test_key_expiring_between_set_and_get_is_claimed_on_the_second_pass():
    assert await IdempotencyGuard(ExpiringStore()).claim(KEY, ALICE) is None


class NeverClaimableStore(ExpiringStore):
    async def set(self, name, value, ex=None, nx=False):
        return False


async def test_gives_up_after_two_passes():
    with pytest.raises(IdempotencyConflict, match="could not be claimed"):
        await IdempotencyGuard(NeverClaimableStore()).claim(KEY, ALICE)
