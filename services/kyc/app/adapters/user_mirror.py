"""The ``auth.users.kyc_status`` claim mirror and the forced token refresh (#40, SDD 4.2.1).

The KYC service is the only writer of ``auth.users.kyc_status`` (a column-level grant to
``kyc_svc`` in infra/postgres/init/10-auth.sql). Every status change also increments
``token_version`` in the same transaction, then the new version is published to Redis as
``tv:{user_id}``. Gates built on ``zeo_common.gateway.require_fresh`` refuse tokens minted
before the change, so the seller refreshes and the new token carries the new status.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from zeo_common.gateway import TokenVersionPublisher

logger = logging.getLogger(__name__)

MIRROR_SQL = (
    "UPDATE auth.users SET kyc_status = $1, kyc_status_updated_at = $2, "
    "token_version = token_version + 1 WHERE id = $3 RETURNING token_version"
)


class UnknownUser(Exception):
    """The submission's user has no auth.users row (deleted, or a bad seed)."""


async def mirror_status(connection: Any, user_id: UUID, status: str, at: datetime) -> int:
    """Write the mirror inside the caller's transaction and return the new token version."""
    version = await connection.fetchval(MIRROR_SQL, status, at, user_id)
    if version is None:
        raise UnknownUser(str(user_id))
    return int(version)


class InMemoryUserMirror:
    """What ``auth.users`` holds for each user, for tests and database-less runs."""

    def __init__(self) -> None:
        self.users: dict[UUID, tuple[str, int]] = {}

    def mirror(self, user_id: UUID, status: str) -> int:
        _, version = self.users.get(user_id, ("NOT_SUBMITTED", 1))
        self.users[user_id] = (status, version + 1)
        return version + 1


class TokenRefreshAnnouncer:
    """Publishes the new version after the transaction commits. A failure is logged, not
    raised: the change is already durable, and tokens expire within 15 minutes anyway."""

    def __init__(self, publisher: TokenVersionPublisher | None) -> None:
        self.publisher = publisher

    async def announce(self, user_id: UUID, version: int) -> None:
        if self.publisher is None:
            return
        try:
            await self.publisher.publish(user_id, version)
        except Exception:
            logger.exception("Publishing token version for user %s failed", user_id)
