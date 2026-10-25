"""Search repository adapter for Search & Analytics (Plan 6, #46, #47).

Database schema: infra/postgres/init/80-search.sql
"""

from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.domain.models import IndexedAuction, SearchQuery, SearchResult, SortOption


class SearchRepository(Protocol):
    async def upsert(self, auction: IndexedAuction) -> IndexedAuction: ...
    async def delete(self, auction_id: UUID) -> None: ...
    async def search(self, query: SearchQuery) -> SearchResult: ...
    async def get_seller_listings(self, seller_id: UUID) -> list[IndexedAuction]: ...


class InMemorySearchRepository:
    def __init__(self) -> None:
        self._store: dict[UUID, IndexedAuction] = {}

    async def upsert(self, auction: IndexedAuction) -> IndexedAuction:
        self._store[auction.auction_id] = auction
        return auction

    async def delete(self, auction_id: UUID) -> None:
        self._store.pop(auction_id, None)

    async def search(self, query: SearchQuery) -> SearchResult:
        items = list(self._store.values())

        # Text filter (simple substring match for in-memory)
        if query.q:
            q_lower = query.q.lower()
            items = [
                a for a in items
                if q_lower in a.title.lower()
                or q_lower in a.category.lower()
                or q_lower in a.description.lower()
            ]

        # Category filter
        if query.category:
            items = [a for a in items if a.category.lower() == query.category.lower()]

        # Price filters
        if query.price_min is not None:
            items = [a for a in items if a.current_price >= query.price_min]
        if query.price_max is not None:
            items = [a for a in items if a.current_price <= query.price_max]

        # Status filter
        if query.status:
            items = [a for a in items if a.state.upper() == query.status.upper()]

        # Sort
        if query.sort == SortOption.ENDING_SOONEST:
            items = sorted(
                items,
                key=lambda a: (a.closes_at is None, a.closes_at),
            )
        elif query.sort == SortOption.NEWEST:
            items = sorted(
                items,
                key=lambda a: (a.created_at is None, a.created_at),
                reverse=True,
            )
        elif query.sort == SortOption.PRICE_ASC:
            items = sorted(items, key=lambda a: a.current_price)
        elif query.sort == SortOption.PRICE_DESC:
            items = sorted(items, key=lambda a: a.current_price, reverse=True)

        total = len(items)
        page_size = min(query.page_size, 100)
        offset = (query.page - 1) * page_size
        page_items = items[offset : offset + page_size]

        return SearchResult(
            items=page_items,
            total=total,
            page=query.page,
            page_size=page_size,
        )

    async def get_seller_listings(self, seller_id: UUID) -> list[IndexedAuction]:
        return [a for a in self._store.values() if a.seller_id == seller_id]


class PostgresSearchRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def upsert(self, auction: IndexedAuction) -> IndexedAuction:
        query = (
            "INSERT INTO search.auction_index "
            "(auction_id, seller_id, title, description, category, current_price, currency, "
            "state, opens_at, closes_at, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) "
            "ON CONFLICT (auction_id) DO UPDATE SET "
            "seller_id = EXCLUDED.seller_id, title = EXCLUDED.title, "
            "description = EXCLUDED.description, category = EXCLUDED.category, "
            "current_price = EXCLUDED.current_price, currency = EXCLUDED.currency, "
            "state = EXCLUDED.state, opens_at = EXCLUDED.opens_at, "
            "closes_at = EXCLUDED.closes_at, updated_at = EXCLUDED.updated_at"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                auction.auction_id,
                auction.seller_id,
                auction.title,
                auction.description,
                auction.category,
                auction.current_price,
                auction.currency,
                auction.state,
                auction.opens_at,
                auction.closes_at,
                auction.created_at,
                auction.updated_at,
            )
        return auction

    async def delete(self, auction_id: UUID) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM search.auction_index WHERE auction_id = $1", auction_id
            )

    async def search(self, query: SearchQuery) -> SearchResult:
        conditions: list[str] = []
        params: list[Any] = []

        if query.q:
            params.append(query.q)
            conditions.append(
                f"search_vector @@ plainto_tsquery('english', ${len(params)})"
            )

        if query.category:
            params.append(query.category)
            conditions.append(f"category = ${len(params)}")

        if query.price_min is not None:
            params.append(query.price_min)
            conditions.append(f"current_price >= ${len(params)}")

        if query.price_max is not None:
            params.append(query.price_max)
            conditions.append(f"current_price <= ${len(params)}")

        if query.status:
            params.append(query.status)
            conditions.append(f"state = ${len(params)}")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sort_map = {
            SortOption.ENDING_SOONEST: "closes_at ASC NULLS LAST",
            SortOption.NEWEST: "created_at DESC NULLS LAST",
            SortOption.PRICE_ASC: "current_price ASC",
            SortOption.PRICE_DESC: "current_price DESC",
        }
        order_by = sort_map.get(query.sort, "closes_at ASC NULLS LAST")

        page_size = min(query.page_size, 100)
        offset = (query.page - 1) * page_size
        params.append(page_size)
        params.append(offset)

        base = f"FROM search.auction_index {where}"  # noqa: S608
        count_q = f"SELECT COUNT(*) {base}"
        data_q = (
            f"SELECT * {base} ORDER BY {order_by} "  # noqa: S608
            f"LIMIT ${len(params) - 1} OFFSET ${len(params)}"
        )

        async with self.pool.acquire() as conn:
            total = await conn.fetchval(count_q, *params[:-2])
            rows = await conn.fetch(data_q, *params)

        return SearchResult(
            items=[_row_to_auction(r) for r in rows],
            total=total or 0,
            page=query.page,
            page_size=page_size,
        )

    async def get_seller_listings(self, seller_id: UUID) -> list[IndexedAuction]:
        query = (
            "SELECT * FROM search.auction_index WHERE seller_id = $1 ORDER BY created_at DESC"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, seller_id)
        return [_row_to_auction(r) for r in rows]


def _row_to_auction(row: Any) -> IndexedAuction:
    return IndexedAuction(
        auction_id=row["auction_id"],
        seller_id=row["seller_id"],
        title=row["title"],
        description=row["description"],
        category=row["category"],
        current_price=Decimal(str(row["current_price"])),
        currency=row["currency"],
        state=row["state"],
        opens_at=row["opens_at"],
        closes_at=row["closes_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
