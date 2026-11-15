"""Auction persistence: PostgreSQL for real, in-memory for tests and database-less runs.

Every write uses optimistic locking on ``version`` (state-machine rule 3): the UPDATE names the
version it read, and 0 rows changed means another writer won, so the caller re-reads and
re-evaluates its guard (:class:`StaleAuction`). Transitions are recorded in the append-only
``auction_state_transitions`` table in the same transaction (rule 2). Recording a bid that
does not change the state (:meth:`record_bid`) writes no transition row.

Listing photos (``auction_images``) are rows of their own: adding or removing one is not a
transition and does not touch the auction's ``version``. Two uploads racing for the same slot
are separated by the ``(auction_id, position)`` unique constraint (:class:`ImageSlotTaken`).
"""

from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from app.domain.auction import Auction
from app.domain.images import ListingImage

_COLUMNS = (
    "id, seller_id, title, description, category, starting_price, reserve_price, currency, "
    "state, opens_at, closes_at, guard_interval_seconds, extension_seconds, max_extensions, "
    "extension_count, created_at, updated_at, version, original_closes_at, winning_bid_id, "
    "last_bid_seq, leading_bid_id, closing_since, leading_bidder_id, leading_amount, "
    "settlement_order_id"
)
_INSERT_TRANSITION = (
    "INSERT INTO auction.auction_state_transitions "
    "(auction_id, event, from_state, to_state, actor_id, at) "
    "VALUES ($1, $2, $3, $4, $5, $6)"
)
_IMAGE_COLUMNS = "id, auction_id, object_key, position, mime_type, size_bytes, uploaded_at"
# Every column a transition or a bid record may change; the rest are fixed at creation.
_UPDATE = (
    "UPDATE auction.auctions SET state = $1, opens_at = $2, closes_at = $3, "
    "original_closes_at = $4, "
    "extension_count = $5, winning_bid_id = $6, last_bid_seq = $7, leading_bid_id = $8, "
    "closing_since = $9, leading_bidder_id = $10, leading_amount = $11, "
    "settlement_order_id = $12, version = $13 WHERE id = $14 AND version = $15"
)


class StaleAuction(Exception):
    """Another transition won the race; re-read and re-evaluate the guard."""


class ImageSlotTaken(Exception):
    """Another upload took the same position first; re-read the photos and retry."""


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

    async def images(self, auction_id: UUID) -> list[ListingImage]:
        """The auction's photos in display order."""
        ...

    async def add_image(self, image: ListingImage) -> None: ...

    async def remove_image(self, auction_id: UUID, image_id: UUID) -> ListingImage | None: ...


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
        self.photos: dict[UUID, ListingImage] = {}

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

    async def images(self, auction_id: UUID) -> list[ListingImage]:
        found = [i for i in self.photos.values() if i.auction_id == auction_id]
        return sorted(found, key=lambda i: i.position)

    async def add_image(self, image: ListingImage) -> None:
        if any(i.position == image.position for i in await self.images(image.auction_id)):
            raise ImageSlotTaken(str(image.auction_id))
        self.photos[image.id] = image

    async def remove_image(self, auction_id: UUID, image_id: UUID) -> ListingImage | None:
        image = self.photos.get(image_id)
        if image is None or image.auction_id != auction_id:
            return None
        return self.photos.pop(image_id)

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
                f"INSERT INTO auction.auctions ({_COLUMNS}) VALUES "  # noqa: S608 - constant column list
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
                f"SELECT {_COLUMNS} FROM auction.auctions WHERE id = $1",  # noqa: S608 - constant columns
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
                f"SELECT {_COLUMNS} FROM auction.auctions WHERE "  # noqa: S608 - constant columns
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
                f"SELECT {_COLUMNS} FROM auction.auctions WHERE "  # noqa: S608 - constant columns
                "state = 'CLOSED' AND winning_bid_id IS NOT NULL AND settlement_order_id IS NULL "
                "ORDER BY updated_at LIMIT $1",
                limit,
            )
        return [_row_to_auction(row) for row in rows]

    async def images(self, auction_id: UUID) -> list[ListingImage]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {_IMAGE_COLUMNS} FROM auction.auction_images "  # noqa: S608 - constant columns
                "WHERE auction_id = $1 ORDER BY position",
                auction_id,
            )
        return [ListingImage(**dict(row)) for row in rows]

    async def add_image(self, image: ListingImage) -> None:
        async with self.pool.acquire() as connection:
            try:
                await connection.execute(
                    f"INSERT INTO auction.auction_images ({_IMAGE_COLUMNS}) "  # noqa: S608 - constant
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    image.id, image.auction_id, image.object_key, image.position,
                    image.mime_type, image.size_bytes, image.uploaded_at,
                )
            except asyncpg.UniqueViolationError as exc:  # (auction_id, position)
                raise ImageSlotTaken(str(image.auction_id)) from exc

    async def remove_image(self, auction_id: UUID, image_id: UUID) -> ListingImage | None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                f"DELETE FROM auction.auction_images WHERE id = $1 AND auction_id = $2 "  # noqa: S608
                f"RETURNING {_IMAGE_COLUMNS}",
                image_id, auction_id,
            )
        return None if row is None else ListingImage(**dict(row))
