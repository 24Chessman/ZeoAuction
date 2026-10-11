"""``server_seq`` allocation, FR-BID-3 / ADR-0001 (#20).

``server_seq`` is the authoritative per-auction order. It is allocated by the server
(``INCR seq:{auction_id}``) before the compare-and-set and before persistence, so the order
is fixed the moment a bid is sequenced and never depends on clocks or arrival at the
database. Numbers are unique and increasing per auction but not gap-free: a bid that loses
the compare-and-set, or whose publish fails, leaves its number unused. Consumers order by
``server_seq`` and never assume contiguity.
"""

from typing import Protocol
from uuid import UUID


class SequenceStore(Protocol):
    async def next_seq(self, auction_id: UUID) -> int: ...


class SequenceAllocator:
    def __init__(self, store: SequenceStore) -> None:
        self.store = store

    async def allocate(self, auction_id: UUID) -> int:
        seq = await self.store.next_seq(auction_id)
        if seq < 1:
            raise RuntimeError(f"sequence store returned {seq} for {auction_id}")
        return seq
