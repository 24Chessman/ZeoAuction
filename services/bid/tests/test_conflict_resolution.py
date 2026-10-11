import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import fakeredis
import pytest

from app.adapters.price_buffer import RedisPriceBuffer, seq_key
from app.adapters.pricing_client import tier_increment
from app.domain.conflict import ConflictResolver, ContentionExceeded, Threshold, replay
from app.domain.model import Leader
from app.domain.sequencing import SequenceAllocator
from app.domain.validation import minimum_next_bid
from app.errors import BidRejected
from tests.fakes import AUCTION_ID

STARTING = Decimal("100.00")


async def threshold_for(leader):
    increment = tier_increment(leader.amount) if leader else Decimal("0")
    return Threshold(minimum_next_bid(leader.amount if leader else None, STARTING, increment))


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def buffer(redis):
    return RedisPriceBuffer(redis)


def resolver(store, **kwargs):
    return ConflictResolver(store, SequenceAllocator(store), **kwargs)


async def place(res, store, amount, *, closes_at=None, bidder=None):
    leader = await store.leader(AUCTION_ID)
    return await res.resolve(
        auction_id=AUCTION_ID, bid_id=uuid4(), bidder_id=bidder or uuid4(),
        amount=Decimal(amount), closes_at=closes_at, threshold_for=threshold_for, leader=leader,
    )


async def test_first_bid_is_sequenced_and_becomes_leader(buffer):
    resolution = await place(resolver(buffer), buffer, "100.00")
    assert resolution.accepted.server_seq == 1
    assert resolution.previous is None
    assert resolution.attempts == 1
    assert await buffer.leader(AUCTION_ID) == resolution.accepted


async def test_bids_must_beat_the_leader_by_the_increment(buffer):
    res = resolver(buffer)
    await place(res, buffer, "100.00")
    with pytest.raises(BidRejected) as caught:
        await place(res, buffer, "104.99")
    assert caught.value.details == {"min_next_bid": "105.00"}
    accepted = await place(res, buffer, "105.00")
    assert accepted.accepted.server_seq == 2  # the rejected bid never allocated a number


async def test_rejected_bid_allocates_no_sequence_number(buffer, redis):
    res = resolver(buffer)
    await place(res, buffer, "100.00")
    with pytest.raises(BidRejected):
        await place(res, buffer, "100.00")
    assert await redis.get(seq_key(AUCTION_ID)) == "1"


class RacingStore:
    """Lets a competing bid win the compare-and-set just before ours runs."""

    def __init__(self, inner, competitor_amount):
        self.inner = inner
        self.competitor_amount = Decimal(competitor_amount)
        self.raced = False

    async def leader(self, auction_id):
        return await self.inner.leader(auction_id)

    async def next_seq(self, auction_id):
        return await self.inner.next_seq(auction_id)

    async def compare_and_set(self, auction_id, expected_seq, new):
        if not self.raced:
            self.raced = True
            competitor = Leader(self.competitor_amount, await self.inner.next_seq(auction_id),
                                uuid4(), uuid4())
            assert await self.inner.compare_and_set(auction_id, expected_seq, competitor)
        return await self.inner.compare_and_set(auction_id, expected_seq, new)


async def test_loser_is_revalidated_and_accepted_at_the_next_seq(buffer):
    await place(resolver(buffer), buffer, "100.00")             # seq 1
    racing = RacingStore(buffer, "105.00")                       # competitor takes seq 3
    resolution = await place(resolver(racing), racing, "120.00")  # ours took seq 2, lost
    assert resolution.attempts == 2
    assert resolution.accepted.server_seq == 4
    assert resolution.previous.amount == Decimal("105.00")
    assert await buffer.leader(AUCTION_ID) == resolution.accepted


async def test_loser_below_the_new_minimum_is_rejected(buffer):
    await place(resolver(buffer), buffer, "100.00")
    racing = RacingStore(buffer, "105.00")
    with pytest.raises(BidRejected) as caught:
        await place(resolver(racing), racing, "105.00")
    assert caught.value.code == "BID_BELOW_INCREMENT"
    assert caught.value.details == {"min_next_bid": "110.00"}
    assert (await buffer.leader(AUCTION_ID)).amount == Decimal("105.00")


async def test_simultaneous_equal_bids_have_exactly_one_winner(buffer):
    res = resolver(buffer)

    async def attempt():
        try:
            return await place(res, buffer, "100.00")
        except BidRejected as rejected:
            return rejected

    outcomes = await asyncio.gather(*(attempt() for _ in range(25)))
    winners = [o for o in outcomes if not isinstance(o, BidRejected)]
    assert len(winners) == 1
    assert {o.code for o in outcomes if isinstance(o, BidRejected)} == {"BID_BELOW_INCREMENT"}
    assert await buffer.leader(AUCTION_ID) == winners[0].accepted


async def test_bid_after_close_is_auction_closed_and_unsequenced(buffer, redis):
    closes_at = datetime.now(UTC) - timedelta(milliseconds=1)
    with pytest.raises(BidRejected) as caught:
        await place(resolver(buffer), buffer, "100.00", closes_at=closes_at)
    assert (caught.value.code, caught.value.status_code) == ("AUCTION_CLOSED", 409)
    assert await redis.get(seq_key(AUCTION_ID)) is None


class AlwaysLosingStore(RacingStore):
    async def compare_and_set(self, auction_id, expected_seq, new):
        return False


async def test_endless_contention_gives_up(buffer):
    store = AlwaysLosingStore(buffer, "0")
    with pytest.raises(ContentionExceeded):
        await place(resolver(store, max_attempts=3), store, "100.00")


def bid(amount, seq):
    return Leader(Decimal(amount), seq, uuid4(), uuid4())


def test_replay_orders_by_server_seq_not_arrival():
    log = [bid("110.00", 3), bid("100.00", 1), bid("105.00", 2)]
    assert replay(log, STARTING, tier_increment) == log[0]


def test_replay_skips_bids_that_do_not_beat_the_leader():
    first = bid("100.00", 1)
    assert replay([first, bid("100.00", 2), bid("104.00", 3)], STARTING, tier_increment) == first


def test_replay_of_nothing_has_no_winner():
    assert replay([], STARTING, tier_increment) is None
    assert replay([bid("99.99", 1)], STARTING, tier_increment) is None
