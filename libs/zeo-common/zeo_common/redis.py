"""Redis client and readiness check.

Redis holds hot, rebuildable state only (SDD Table 4.3): ``price:{auction_id}``,
``seq:{auction_id}``, ``idem:{key}``, ``inc:{auction_id}``, ``ws:room:{auction_id}`` and
``flush:pending``. Nothing in Redis is authoritative; Kafka and PostgreSQL can rebuild it.
"""

from typing import Any

from redis import asyncio as aioredis

from zeo_common.health import ReadinessCheck


def create_redis(url: str) -> aioredis.Redis:
    """Client that returns ``str`` rather than ``bytes``; every value we store is text."""
    return aioredis.from_url(url, decode_responses=True)


def redis_check(client: Any) -> ReadinessCheck:
    """A ``/readyz`` check that pings Redis."""

    async def check() -> bool:
        return bool(await client.ping())

    return check
