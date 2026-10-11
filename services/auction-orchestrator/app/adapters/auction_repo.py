"""Auction persistence: PostgreSQL for real, in-memory for tests and database-less runs.

Every write uses optimistic locking on ``version`` (state-machine rule 3): the UPDATE names the
version it read, and 0 rows changed means another writer won, so the caller re-reads and
re-evaluates its guard (:class:`StaleAuction`). Transitions are recorded in the append-only
``auction_state_transitions`` table in the same transaction (rule 2). Recording a bid that
does not change the state (:meth:`record_bid`) writes no transition row.
"""

from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.domain.auction import Auction

_COLUMNS = (
    "id, seller_id, title, description, category, starting_price, reserve_price, currency, "
    "state, opens_at, closes_at, guard_interval_seconds, extension_seconds, max_extensions, "
    "extension_count, created_at, updated_at, version, original_closes_at, winning_bid_id, "
    "last_bid_seq, leading_bid_id, closing_since, leading_bidder_id, leading_amount, "
    "settlement_order_id"
)
_INSERT_TRANSITION = (
    "INSERT INTO auction_state_transitions (auction_id, event, from_state, to_state, actor_id, at) "
    "VALUES ($1, $2, $3, $4, $5, $6)"
)
# Every column a transition or a bid record may change; the rest are fixed at creation.
_UPDATE = (
    "UPDATE auctions SET state = $1, opens_at = $2, closes_at = $3, original_closes_at = $4, "
    "extension_count = $5, winning_bid_id = $6, last_bid_seq = $7, leading_bid_id = $8, "
    "closing_since = $9, leading_bidder_id = $10, leading_amount = $11, "
    "settlement_order_id = $12, version = $13 WHERE id = $14 AND version = $15"
)


class StaleAuction(Exception):
    """Another transition won the race; re-read and re-evaluate the guard."""


class AuctionRepository(Protocol):
    async def add(self, auction: Auction) -> None: ...

    async def get(self, auction_id: UUID) -> Auction | None: ...

    async def save_transition(
        self, before: Auction, after: Auction, event: str, actor_id: UUID | None
    ) -> None: ...

    async def record_bid(self, before: Auction, after: Auction) -> None: ...

    async def record_settlement(self, before: Auction, after: Auction) -> None:
        """Save ``settlement_order_id``; like a bid record, it is not a transition."""
        ...

    async def due(self, now: datetime, drain_grace: timedelta,
                  limit: int) -> list[tuple[Auction, str]]: ...

    async def awaiting_settlement(self, limit: int) -> list[Auction]:
        """CLOSED auctions with a winner whose order Payment has not opened yet."""
        ...


def due_event(auction: Auction, now: datetime, drain_grace: timedelta) -> str | None:
    """The timer event an auction is waiting for, if its moment has come (A2, A5, A6)."""
    if auction.state == "SCHEDULED" and auction.opens_at and auction.opens_at <= now:
        return "open"
    if auction.state in ("OPEN", "EXTENDED") and auction.closes_at and auction.closes_at <= now:
        return "close"
    if auction.state == "CLOSING" and (
        auction.closing_since is None or auction.closing_since + drain_grace <= now
    ):
        return "drained"
    return None


class InMemoryAuctionRepository:
    def __init__(self) -> None:
        self.auctions: dict[UUID, Auction] = {}
        self.transitions: list[tuple[UUID, str, str | None, str, UUID | None]] = []

    async def add(self, auction: Auction) -> None:
        self.auctions[auction.id] = auction
        self.transitions.append((auction.id, "create", None, auction.state, auction.seller_id))

    async def get(self, auction_id: UUID) -> Auction | None:
        return self.auctions.get(auction_id)

    def _swap(self, before: Auction, after: Auction) -> None:
        current = self.auctions.get(before.id)
        if current is None or current.version != before.version:
            raise StaleAuction(str(before.id))
        self.auctions[after.id] = after

    async def save_transition(
        self, before: Auction, after: Auction, event: str, actor_id: UUID | None
    ) -> None:
        self._swap(before, after)
        self.transitions.append((after.id, event, before.state, after.state, actor_id))

    async def record_bid(self, before: Auction, after: Auction) -> None:
        self._swap(before, after)

    async def record_settlement(self, before: Auction, after: Auction) -> None:
        self._swap(before, after)

    async def due(self, now: datetime, drain_grace: timedelta,
                  limit: int) -> list[tuple[Auction, str]]:
        found = []
        for auction in sorted(self.auctions.values(), key=lambda a: a.created_at):
            event = due_event(auction, now, drain_grace)
            if event:
                found.append((auction, event))
        return found[:limit]

    async def awaiting_settlement(self, limit: int) -> list[Auction]:
        waiting = [a for a in self.auctions.values() if a.awaiting_settlement]
        return sorted(waiting, key=lambda a: a.updated_at)[:limit]

    def lifecycle(self, auction_id: UUID) -> list[str]:
        """The recorded events of one auction, for tests."""
        return [event for aid, event, *_ in self.transitions if aid == auction_id]


def _row_to_auction(row: Any) -> Auction:
    return Auction(**dict(row))


def _update_args(before: Auction, after: Auction) -> tuple:
    return (
        after.state, after.opens_at, after.closes_at, after.original_closes_at,
        after.extension_count, after.winning_bid_id, after.last_bid_seq, after.leading_bid_id,
        after.closing_since, after.leading_bidder_id, after.leading_amount,
        after.settlement_order_id, after.version, before.id, before.version,
    )


class PostgresAuctionRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def add(self, auction: Auction) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                f"INSERT INTO auctions ({_COLUMNS}) VALUES "  # noqa: S608 - constant column list
                "($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, "
                "$18, $19, $20, $21, $22, $23, $24, $25, $26)",
                auction.id, auction.seller_id, auction.title, auction.description,
                auction.category, auction.starting_price, auction.reserve_price,
                auction.currency, auction.state, auction.opens_at, auction.closes_at,
                auction.guard_interval_seconds, auction.extension_seconds,
                auction.max_extensions, auction.extension_count, auction.created_at,
                auction.updated_at, auction.version, auction.original_closes_at,
                auction.winning_bid_id, auction.last_bid_seq, auction.leading_bid_id,
                auction.closing_since, auction.leading_bidder_id, auction.leading_amount,
                auction.settlement_order_id,
            )
            await connection.execute(
                _INSERT_TRANSITION, auction.id, "create", None, auction.state,
                auction.seller_id, auction.created_at,
            )

    async def get(self, auction_id: UUID) -> Auction | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_COLUMNS} FROM auctions WHERE id = $1",  # noqa: S608 - constant columns
                auction_id,
            )
        return None if row is None else _row_to_auction(row)

    async def save_transition(
        self, before: Auction, after: Auction, event: str, actor_id: UUID | None
    ) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            status = await connection.execute(_UPDATE, *_update_args(before, after))
            if status != "UPDATE 1":
                raise StaleAuction(str(before.id))
            await connection.execute(
                _INSERT_TRANSITION, after.id, event, before.state, after.state, actor_id,
                after.updated_at,
            )

    async def record_bid(self, before: Auction, after: Auction) -> None:
        async with self.pool.acquire() as connection:
            status = await connection.execute(_UPDATE, *_update_args(before, after))
        if status != "UPDATE 1":
            raise StaleAuction(str(before.id))

    async def record_settlement(self, before: Auction, after: Auction) -> None:
        await self.record_bid(before, after)

    async def due(self, now: datetime, drain_grace: timedelta,
                  limit: int) -> list[tuple[Auction, str]]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_COLUMNS} FROM auctions WHERE "  # noqa: S608 - constant columns
                "(state = 'SCHEDULED' AND opens_at <= $1) "
                "OR (state IN ('OPEN', 'EXTENDED') AND closes_at <= $1) "
                "OR (state = 'CLOSING' AND (closing_since IS NULL OR closing_since <= $2)) "
                "ORDER BY created_at LIMIT $3",
                now, now - drain_grace, limit,
            )
        found = []
        for row in rows:
            auction = _row_to_auction(row)
            event = due_event(auction, now, drain_grace)
            if event:
                found.append((auction, event))
        return found

    async def awaiting_settlement(self, limit: int) -> list[Auction]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_COLUMNS} FROM auctions WHERE "  # noqa: S608 - constant columns
                "state = 'CLOSED' AND winning_bid_id IS NOT NULL AND settlement_order_id IS NULL "
                "ORDER BY updated_at LIMIT $1",
                limit,
            )
        return [_row_to_auction(row) for row in rows]
