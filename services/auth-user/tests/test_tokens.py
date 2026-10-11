import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.refresh_tokens import (
    InMemoryRefreshTokenStore,
    RefreshTokenError,
    RefreshTokens,
)
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import hash_refresh_token, new_refresh_token


class Clock:
    def __init__(self):
        self.now = datetime(2026, 8, 20, tzinfo=UTC)

    def __call__(self):
        return self.now


@pytest.fixture
def store():
    return InMemoryRefreshTokenStore()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tokens(store, clock):
    return RefreshTokens(store, timedelta(days=14), clock)


async def test_rotation_issues_a_new_token_in_the_same_family(tokens, store):
    user = uuid4()
    first = await tokens.issue(user)
    owner, second = await tokens.rotate(first)
    assert owner == user and second != first
    old = await store.get_by_hash(hash_refresh_token(first))
    new = await store.get_by_hash(hash_refresh_token(second))
    assert old.rotated_at is not None and old.replaced_by == new.id
    assert old.family_id == new.family_id


async def test_reuse_revokes_the_whole_family(tokens, store):
    first = await tokens.issue(uuid4())
    _, second = await tokens.rotate(first)
    with pytest.raises(RefreshTokenError) as caught:
        await tokens.rotate(first)
    assert caught.value.code == "REFRESH_TOKEN_REUSED"
    assert all(r.revoked_at is not None for r in store.records.values())
    with pytest.raises(RefreshTokenError):
        await tokens.rotate(second)


async def test_other_families_survive_a_reuse(tokens):
    user = uuid4()
    phone, laptop = await tokens.issue(user), await tokens.issue(user)
    await tokens.rotate(phone)
    with pytest.raises(RefreshTokenError):
        await tokens.rotate(phone)
    owner, _ = await tokens.rotate(laptop)
    assert owner == user


async def test_concurrent_use_of_one_token_counts_as_reuse(tokens):
    token = await tokens.issue(uuid4())
    results = await asyncio.gather(tokens.rotate(token), tokens.rotate(token),
                                   return_exceptions=True)
    assert sum(isinstance(r, RefreshTokenError) for r in results) >= 1


async def test_expired_token_is_invalid(tokens, clock):
    token = await tokens.issue(uuid4())
    clock.now += timedelta(days=14, seconds=1)
    with pytest.raises(RefreshTokenError) as caught:
        await tokens.rotate(token)
    assert caught.value.code == "REFRESH_TOKEN_INVALID"


async def test_only_the_hash_is_stored(tokens, store):
    token = await tokens.issue(uuid4())
    (record,) = store.records.values()
    assert record.token_hash == hash_refresh_token(token)
    assert token not in str(record)


async def test_revoke_ends_the_family(tokens):
    token = await tokens.issue(uuid4())
    await tokens.revoke(token)
    with pytest.raises(RefreshTokenError):
        await tokens.rotate(token)


def test_refresh_tokens_are_long_and_unique():
    batch = {new_refresh_token() for _ in range(1000)}
    assert len(batch) == 1000
    assert all(len(t) >= 43 for t in batch)


def test_password_hash_round_trip():
    stored = hash_password("correct-horse-42")
    assert stored.startswith("scrypt$16384$8$1$")
    assert verify_password("correct-horse-42", stored)
    assert not verify_password("correct-horse-43", stored)
    assert hash_password("correct-horse-42") != stored  # salted


@pytest.mark.parametrize("stored", ["!seed", "", "bcrypt$x", "scrypt$1$2$3$!!$!!", "scrypt$a$b"])
def test_malformed_hashes_never_verify(stored):
    assert verify_password("anything", stored) is False


def test_needs_rehash_for_other_parameters():
    assert needs_rehash("scrypt$1024$8$1$c2FsdA==$aGFzaA==")
    assert not needs_rehash(hash_password("correct-horse-42"))
