"""Admin & Moderation repository (Plan 6, #81, #82, #83).

Database schema: infra/postgres/init/85-admin.sql
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.domain.listing_review import ListingReview, ReviewSource, ReviewState
from app.domain.suspension import SuspensionReasonCode, UserSuspension


@dataclass(frozen=True)
class Broadcast:
    id: UUID
    title: str
    body: str
    created_by: UUID
    created_at: datetime


class AdminRepository(Protocol):
    async def save_suspension(self, suspension: UserSuspension) -> UserSuspension: ...
    async def get_active_suspension(self, user_id: UUID) -> UserSuspension | None: ...
    async def update_suspension(self, suspension: UserSuspension) -> UserSuspension: ...
    async def save_review(self, review: ListingReview) -> ListingReview: ...
    async def get_review(self, review_id: UUID) -> ListingReview | None: ...
    async def list_pending_reviews(self) -> list[ListingReview]: ...
    async def update_review(self, review: ListingReview) -> ListingReview: ...
    async def save_broadcast(self, broadcast: Broadcast) -> Broadcast: ...
    async def list_broadcasts(self, limit: int = 20) -> list[Broadcast]: ...
    async def get_audit_log(
        self,
        *,
        target_type: str | None = None,
        target_id: UUID | None = None,
        actor_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...


class InMemoryAdminRepository:
    def __init__(self) -> None:
        self.suspensions: dict[UUID, UserSuspension] = {}
        self.reviews: dict[UUID, ListingReview] = {}
        self.broadcasts: list[Broadcast] = []
        self.audit_log: list[dict[str, Any]] = []

    async def save_suspension(self, suspension: UserSuspension) -> UserSuspension:
        self.suspensions[suspension.id] = suspension
        return suspension

    async def get_active_suspension(self, user_id: UUID) -> UserSuspension | None:
        for s in self.suspensions.values():
            if s.user_id == user_id and s.is_active:
                return s
        return None

    async def update_suspension(self, suspension: UserSuspension) -> UserSuspension:
        self.suspensions[suspension.id] = suspension
        return suspension

    async def save_review(self, review: ListingReview) -> ListingReview:
        self.reviews[review.id] = review
        return review

    async def get_review(self, review_id: UUID) -> ListingReview | None:
        return self.reviews.get(review_id)

    async def list_pending_reviews(self) -> list[ListingReview]:
        return [r for r in self.reviews.values() if r.state == ReviewState.PENDING]

    async def update_review(self, review: ListingReview) -> ListingReview:
        self.reviews[review.id] = review
        return review

    async def save_broadcast(self, broadcast: Broadcast) -> Broadcast:
        self.broadcasts.append(broadcast)
        return broadcast

    async def list_broadcasts(self, limit: int = 20) -> list[Broadcast]:
        return sorted(self.broadcasts, key=lambda b: b.created_at, reverse=True)[:limit]

    async def get_audit_log(
        self,
        *,
        target_type: str | None = None,
        target_id: UUID | None = None,
        actor_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        entries = self.audit_log
        if target_type:
            entries = [e for e in entries if e.get("target_type") == target_type]
        if target_id:
            entries = [e for e in entries if e.get("target_id") == str(target_id)]
        if actor_id:
            entries = [e for e in entries if e.get("actor_id") == str(actor_id)]
        return entries[offset : offset + limit]


class PostgresAdminRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def save_suspension(self, suspension: UserSuspension) -> UserSuspension:
        query = (
            "INSERT INTO admin.user_suspensions (id, user_id, reason_code, note, suspended_by, "
            "suspended_at, lifted_by, lifted_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                suspension.id,
                suspension.user_id,
                str(suspension.reason_code),
                suspension.note,
                suspension.suspended_by,
                suspension.suspended_at,
                suspension.lifted_by,
                suspension.lifted_at,
            )
        return suspension

    async def get_active_suspension(self, user_id: UUID) -> UserSuspension | None:
        query = (
            "SELECT * FROM admin.user_suspensions WHERE user_id = $1 AND lifted_at IS NULL"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, user_id)
            if not row:
                return None
            return UserSuspension(
                id=row["id"],
                user_id=row["user_id"],
                reason_code=SuspensionReasonCode(row["reason_code"]),
                note=row["note"],
                suspended_by=row["suspended_by"],
                suspended_at=row["suspended_at"],
                lifted_by=row["lifted_by"],
                lifted_at=row["lifted_at"],
            )

    async def update_suspension(self, suspension: UserSuspension) -> UserSuspension:
        query = (
            "UPDATE admin.user_suspensions SET lifted_by = $1, lifted_at = $2 WHERE id = $3"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(query, suspension.lifted_by, suspension.lifted_at, suspension.id)
        return suspension

    async def save_review(self, review: ListingReview) -> ListingReview:
        query = (
            "INSERT INTO admin.listing_reviews (id, auction_id, source, reported_by, reason, "
            "state, reviewed_by, decided_at, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                review.id,
                review.auction_id,
                str(review.source),
                review.reported_by,
                review.reason,
                str(review.state),
                review.reviewed_by,
                review.decided_at,
                review.created_at,
            )
        return review

    async def get_review(self, review_id: UUID) -> ListingReview | None:
        query = "SELECT * FROM admin.listing_reviews WHERE id = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, review_id)
            if not row:
                return None
            return ListingReview(
                id=row["id"],
                auction_id=row["auction_id"],
                source=ReviewSource(row["source"]),
                reported_by=row["reported_by"],
                reason=row["reason"],
                state=ReviewState(row["state"]),
                reviewed_by=row["reviewed_by"],
                decided_at=row["decided_at"],
                created_at=row["created_at"],
            )

    async def list_pending_reviews(self) -> list[ListingReview]:
        query = "SELECT * FROM admin.listing_reviews WHERE state = 'PENDING' ORDER BY created_at ASC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [
                ListingReview(
                    id=row["id"],
                    auction_id=row["auction_id"],
                    source=ReviewSource(row["source"]),
                    reported_by=row["reported_by"],
                    reason=row["reason"],
                    state=ReviewState(row["state"]),
                    reviewed_by=row["reviewed_by"],
                    decided_at=row["decided_at"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def update_review(self, review: ListingReview) -> ListingReview:
        query = (
            "UPDATE admin.listing_reviews SET state = $1, reviewed_by = $2, decided_at = $3 "
            "WHERE id = $4"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                str(review.state),
                review.reviewed_by,
                review.decided_at,
                review.id,
            )
        return review

    async def save_broadcast(self, broadcast: Broadcast) -> Broadcast:
        query = (
            "INSERT INTO admin.broadcasts (id, title, body, created_by, created_at) "
            "VALUES ($1, $2, $3, $4, $5)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                broadcast.id,
                broadcast.title,
                broadcast.body,
                broadcast.created_by,
                broadcast.created_at,
            )
        return broadcast

    async def list_broadcasts(self, limit: int = 20) -> list[Broadcast]:
        query = "SELECT * FROM admin.broadcasts ORDER BY created_at DESC LIMIT $1"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
            return [
                Broadcast(
                    id=row["id"],
                    title=row["title"],
                    body=row["body"],
                    created_by=row["created_by"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def get_audit_log(
        self,
        *,
        target_type: str | None = None,
        target_id: UUID | None = None,
        actor_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = []
        params = []
        if target_type:
            params.append(target_type)
            conditions.append(f"target_type = ${len(params)}")
        if target_id:
            params.append(target_id)
            conditions.append(f"target_id = ${len(params)}")
        if actor_id:
            params.append(actor_id)
            conditions.append(f"actor_id = ${len(params)}")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        query = f"SELECT * FROM admin.audit_log {where} ORDER BY at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"  # noqa: S608

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]
