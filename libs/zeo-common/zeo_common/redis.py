"""Redis client and readiness check.

Redis holds hot, rebuildable state only (SDD Table 4.3): ``price:{auction_id}``,
``seq:{auction_id}``, ``idem:{key}``, ``inc:{auction_id}``, ``ws:room:{auction_id}`` and
``flush:pending``. Nothing in Redis is authoritative; Kafka and PostgreSQL can rebuild it.

Supports local Redis (``redis://...``), TLS-secured Upstash Redis (``rediss://...``),
and automatically derives the TLS endpoint if ``UPSTASH_REDIS_REST_URL`` and
``UPSTASH_REDIS_REST_TOKEN`` are provided.
"""

import os
from typing import Any

from redis import asyncio as aioredis

from zeo_common.health import ReadinessCheck


def resolve_redis_url(url: str | None = None) -> str:
    """Resolve Redis connection string from url or environment variables."""
    if url and not url.startswith("https://") and not (
        "upstash.io" in url and not url.startswith("redis")
    ):
        return url

    rest_url = url if (url and url.startswith("https://")) else os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip("\"'")
    if rest_url and token:
        clean_host = (
            rest_url.replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
            .strip("\"'")
        )
        return f"rediss://default:{token}@{clean_host}:6379"

    if url:
        return url
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def create_redis(url: str | None = None) -> aioredis.Redis:
    """Client that returns ``str`` rather than ``bytes``; every value we store is text."""
    resolved_url = resolve_redis_url(url)
    return aioredis.from_url(resolved_url, decode_responses=True)


def redis_check(client: Any) -> ReadinessCheck:
    """A ``/readyz`` check that pings Redis."""

    async def check() -> bool:
        return bool(await client.ping())

    return check
