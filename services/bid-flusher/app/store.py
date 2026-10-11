"""Writes to ``bid.bids`` (role ``bid_svc``, shared with the bid service).

Inserts are idempotent (``ON CONFLICT DO NOTHING`` on the primary key, the
``(auction_id, server_seq)`` and the ``idempotency_key`` constraints), so a batch written
twice, by a retry after a crash or by a Kafka replay, never creates a second row.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from zeo_common import parse_money


@dataclass(frozen=True)
class BidRow:
    bid_id: UUID
    auction_id: UUID
    bidder_id: UUID
    amount: Decimal
    server_seq: int
    idempotency_key: str
    device_fingerprint: str | None
    increment_stale: bool
    accepted_at: datetime


def row_from_event(event: dict[str, Any]) -> BidRow:
    """Map a ``BidAccepted v1`` event to its ``bid.bids`` row."""
    return BidRow(
        bid_id=UUID(event["bid_id"]),
        auction_id=UUID(event["auction_id"]),
        bidder_id=UUID(event["bidder_id"]),
        amount=parse_money(event["amount"]),
        server_seq=int(event["server_seq"]),
        idempotency_key=event["idempotency_key"],
        device_fingerprint=event.get("device_fingerprint"),
        increment_stale=bool(event.get("increment_stale", False)),
        accepted_at=datetime.fromisoformat(event["accepted_at"].replace("Z", "+00:00")),
    )


class BidStore(Protocol):
    async def insert_batch(self, rows: list[BidRow]) -> None: ...

    async def max_seq_by_auction(self) -> dict[UUID, int]: ...


class InMemoryBidStore:
    def __init__(self) -> None:
        self.rows: dict[UUID, BidRow] = {}
        self.batches: list[int] = []
        self.fail_next = False

    async def insert_batch(self, rows: list[BidRow]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("database unavailable")
        self.batches.append(len(rows))
        taken = {(r.auction_id, r.server_seq) for r in self.rows.values()}
        keys = {r.idempotency_key for r in self.rows.values()}
        for row in rows:
            if row.bid_id in self.rows or (row.auction_id, row.server_seq) in taken \
                    or row.idempotency_key in keys:
                continue
            self.rows[row.bid_id] = row
            taken.add((row.auction_id, row.server_seq))
            keys.add(row.idempotency_key)

    async def max_seq_by_auction(self) -> dict[UUID, int]:
        result: dict[UUID, int] = {}
        for row in self.rows.values():
            result[row.auction_id] = max(result.get(row.auction_id, 0), row.server_seq)
        return result


class PostgresBidStore:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def insert_batch(self, rows: list[BidRow]) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.executemany(
                "INSERT INTO bids (id, auction_id, bidder_id, amount, server_seq, "
                "idempotency_key, device_fingerprint, increment_stale, accepted_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT DO NOTHING",
                [
                    (r.bid_id, r.auction_id, r.bidder_id, r.amount, r.server_seq,
                     r.idempotency_key, r.device_fingerprint, r.increment_stale, r.accepted_at)
                    for r in rows
                ],
            )

    async def max_seq_by_auction(self) -> dict[UUID, int]:
        async with self.pool.acquire() as connection:
            records = await connection.fetch(
                "SELECT auction_id, max(server_seq) AS seq FROM bids GROUP BY auction_id"
            )
        return {r["auction_id"]: int(r["seq"]) for r in records}
