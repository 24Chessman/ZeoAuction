"""Read side of ``bid.bids``: bid history, one bid, and the durable idempotency backstop.

Rows are written only by the bid-flusher (in batches, after acknowledgement), so a bid that
was accepted moments ago may not be listed yet; ``price:{auction_id}`` is the live view.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class StoredBid:
    bid_id: UUID
    auction_id: UUID
    bidder_id: UUID
    amount: Decimal
    server_seq: int
    accepted_at: datetime
    idempotency_key: str


class BidRepository(Protocol):
    async def get(self, bid_id: UUID) -> StoredBid | None: ...

    async def get_by_idempotency_key(self, key: str) -> StoredBid | None: ...

    async def page(
        self, auction_id: UUID, page: int, page_size: int
    ) -> tuple[list[StoredBid], int]: ...


class InMemoryBidRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, StoredBid] = {}

    def add(self, bid: StoredBid) -> None:
        self.rows[bid.bid_id] = bid

    async def get(self, bid_id: UUID) -> StoredBid | None:
        return self.rows.get(bid_id)

    async def get_by_idempotency_key(self, key: str) -> StoredBid | None:
        return next((b for b in self.rows.values() if b.idempotency_key == key), None)

    async def page(
        self, auction_id: UUID, page: int, page_size: int
    ) -> tuple[list[StoredBid], int]:
        bids = sorted(
            (b for b in self.rows.values() if b.auction_id == auction_id),
            key=lambda b: b.server_seq,
            reverse=True,
        )
        start = (page - 1) * page_size
        return bids[start : start + page_size], len(bids)


_COLUMNS = "id AS bid_id, auction_id, bidder_id, amount, server_seq, accepted_at, idempotency_key"


class PostgresBidRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def _one(self, where: str, value: Any) -> StoredBid | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_COLUMNS} FROM bids WHERE {where} = $1",  # noqa: S608 - constant SQL
                value,
            )
        return None if row is None else StoredBid(**dict(row))

    async def get(self, bid_id: UUID) -> StoredBid | None:
        return await self._one("id", bid_id)

    async def get_by_idempotency_key(self, key: str) -> StoredBid | None:
        return await self._one("idempotency_key", key)

    async def page(
        self, auction_id: UUID, page: int, page_size: int
    ) -> tuple[list[StoredBid], int]:
        async with self.pool.acquire() as connection:
            total = await connection.fetchval(
                "SELECT count(*) FROM bids WHERE auction_id = $1", auction_id
            )
            rows = await connection.fetch(
                f"SELECT {_COLUMNS} FROM bids WHERE auction_id = $1 "  # noqa: S608
                "ORDER BY server_seq DESC LIMIT $2 OFFSET $3",
                auction_id, page_size, (page - 1) * page_size,
            )
        return [StoredBid(**dict(row)) for row in rows], int(total)
