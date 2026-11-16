"""PostgreSQL connection pool and readiness check.

Every service connects as its own login role (``DATABASE_URL``), whose ``search_path`` is its
own schema, so queries use unqualified table names and cannot reach another service's tables
(``infra/postgres/init/00-roles-and-schemas.sql``).

When connecting to NeonDB or shared PostgreSQL instances where all services share one login role
(e.g., ``neondb_owner``), the target schema is extracted from:
  1. Explicit ``schema`` argument, OR
  2. ``currentSchema`` or ``schema`` query parameter in the DSN, OR
  3. ``DATABASE_SCHEMA`` environment variable.
Every pooled connection then runs ``SET search_path = <schema>, public``.
"""

import logging
import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg

from zeo_common.health import ReadinessCheck

logger = logging.getLogger("zeo.db")


def mask_dsn(dsn: str) -> str:
    """Mask password in PostgreSQL DSN for safe logging."""
    try:
        parsed = urlparse(dsn)
        if parsed.password:
            netloc = f"{parsed.username or ''}:****@{parsed.hostname or ''}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
        return dsn
    except Exception:
        return "<dsn>"


async def create_pool(
    dsn: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
    schema: str | None = None,
) -> asyncpg.Pool:
    """Open a pool. ``asyncpg`` returns ``numeric`` as ``Decimal``, so money stays exact."""
    target_schema = schema
    clean_dsn = dsn

    if "?" in dsn:
        parsed = urlparse(dsn)
        qs = parse_qs(parsed.query)
        if not target_schema:
            if "currentSchema" in qs:
                target_schema = qs.pop("currentSchema")[0]
            elif "schema" in qs:
                target_schema = qs.pop("schema")[0]
        else:
            qs.pop("currentSchema", None)
            qs.pop("schema", None)
        # Rebuild DSN without the custom schema parameters
        clean_dsn = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

    if not target_schema:
        target_schema = os.environ.get("DATABASE_SCHEMA")

    async def _init_connection(connection: asyncpg.Connection) -> None:
        if target_schema:
            await connection.execute(f"SET search_path = {target_schema}, public")

    logger.info(
        "Connecting to PostgreSQL at %s (schema=%s, min_size=%d, max_size=%d)",
        mask_dsn(clean_dsn),
        target_schema or "public",
        min_size,
        max_size,
    )

    try:
        pool = await asyncpg.create_pool(
            clean_dsn,
            min_size=min_size,
            max_size=max_size,
            init=_init_connection,
        )
        logger.info(
            "PostgreSQL connection pool established successfully (schema: %s)",
            target_schema or "public",
        )
        return pool
    except Exception as exc:
        logger.exception(
            "Failed to establish PostgreSQL connection pool at %s: %s",
            mask_dsn(clean_dsn),
            exc,
        )
        raise


def postgres_check(pool: Any) -> ReadinessCheck:
    """A ``/readyz`` check that runs ``SELECT 1`` on a pooled connection."""

    async def check() -> bool:
        async with pool.acquire() as connection:
            return await connection.fetchval("SELECT 1") == 1

    return check
