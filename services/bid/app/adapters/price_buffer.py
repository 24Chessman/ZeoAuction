"""Redis current-price buffer and the bounded write queue (#30, ADR-0002, SDD Table 4.3).

Keys this adapter owns:

``price:{auction_id}``  hash ``amount, server_seq, bid_id, bidder_id``: the hot read, i.e. the
                        current leader. Changed only by :meth:`compare_and_set` (a Lua script,
                        so the check and the write are one atomic step).
``seq:{auction_id}``    ``INCR`` counter that allocates ``server_seq``.
``flush:pending``       list of accepted ``BidAccepted v1`` events (JSON) waiting for the
                        bid-flusher, which drains it into ``bid.bids`` in batches bounded by
                        size and age. Only bids already acknowledged by Kafka are queued, so
                        Kafka can always rebuild what Redis loses.

None of these keys is authoritative: the flusher's replay rebuilds them from ``bid.events``.
"""

import json
import time
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.model import Leader
from zeo_common import format_money

FLUSH_PENDING_KEY = "flush:pending"

# Set the leader only if the leader we validated against is still the leader.
# ARGV[1] is the expected leader's server_seq ("0" when the auction had no bids).
_COMPARE_AND_SET = """
local current = redis.call('HGET', KEYS[1], 'server_seq')
if (current == false and ARGV[1] == '0') or current == ARGV[1] then
  redis.call('HSET', KEYS[1], 'amount', ARGV[2], 'server_seq', ARGV[3],
             'bid_id', ARGV[4], 'bidder_id', ARGV[5])
  return 1
end
return 0
"""

# Undo our own leadership after a failed publish, but only if nobody has outbid us since.
# ARGV[1] is our bid_id; ARGV[2..5] the previous leader, or ARGV[2] == "" for none.
_ROLLBACK = """
if redis.call('HGET', KEYS[1], 'bid_id') ~= ARGV[1] then
  return 0
end
if ARGV[2] == '' then
  redis.call('DEL', KEYS[1])
else
  redis.call('HSET', KEYS[1], 'amount', ARGV[2], 'server_seq', ARGV[3],
             'bid_id', ARGV[4], 'bidder_id', ARGV[5])
end
return 1
"""


def price_key(auction_id: UUID) -> str:
    return f"price:{auction_id}"


def seq_key(auction_id: UUID) -> str:
    return f"seq:{auction_id}"


def _leader_args(leader: Leader) -> list[str]:
    return [format_money(leader.amount), str(leader.server_seq), str(leader.bid_id),
            str(leader.bidder_id)]


class RedisPriceBuffer:
    def __init__(self, redis: Any) -> None:
        self.redis = redis
        self._cas = redis.register_script(_COMPARE_AND_SET)
        self._rollback = redis.register_script(_ROLLBACK)

    async def leader(self, auction_id: UUID) -> Leader | None:
        fields = await self.redis.hgetall(price_key(auction_id))
        if not fields:
            return None
        return Leader(
            amount=Decimal(fields["amount"]),
            server_seq=int(fields["server_seq"]),
            bid_id=UUID(fields["bid_id"]),
            bidder_id=UUID(fields["bidder_id"]),
        )

    async def next_seq(self, auction_id: UUID) -> int:
        return int(await self.redis.incr(seq_key(auction_id)))

    async def compare_and_set(self, auction_id: UUID, expected_seq: int, new: Leader) -> bool:
        result = await self._cas(keys=[price_key(auction_id)],
                                 args=[str(expected_seq), *_leader_args(new)])
        return int(result) == 1

    async def rollback(self, auction_id: UUID, ours: Leader, previous: Leader | None) -> bool:
        previous_args = _leader_args(previous) if previous else ["", "", "", ""]
        result = await self._rollback(keys=[price_key(auction_id)],
                                      args=[str(ours.bid_id), *previous_args])
        return int(result) == 1

    async def enqueue_for_flush(self, event: dict[str, Any]) -> None:
        record = {"event": event, "enqueued_at_ms": int(time.time() * 1000)}
        await self.redis.rpush(FLUSH_PENDING_KEY, json.dumps(record, separators=(",", ":")))

    async def pending_depth(self) -> int:
        return int(await self.redis.llen(FLUSH_PENDING_KEY))
