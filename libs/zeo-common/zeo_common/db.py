"""PostgreSQL connection pool and readiness check.

Every service connects as its own login role (``DATABASE_URL``), whose ``search_path`` is its
own schema, so queries use unqualified table names and cannot reach another service's tables
(``infra/postgres/init/00-roles-and-schemas.sql``).
"""

from typing import Any

import asyncpg

from zeo_common.health import ReadinessCheck


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """Open a pool. ``asyncpg`` returns ``numeric`` as ``Decimal``, so money stays exact."""
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)


def postgres_check(pool: Any) -> ReadinessCheck:
    """A ``/readyz`` check that runs ``SELECT 1`` on a pooled connection."""

    async def check() -> bool:
        async with pool.acquire() as connection:
            return await connection.fetchval("SELECT 1") == 1

    return check
