"""Admin & Moderation use cases (Plan 6, #81, #82, #83)."""

from collections.abc import Callable
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID, uuid4

from app.adapters.admin_repo import AdminRepository, Broadcast
from app.domain.listing_review import (
    ListingReview,
    ReviewSource,
    ReviewState,
    approve_listing as domain_approve,
    create_review as domain_create_review,
    remove_listing as domain_remove,
)
from app.domain.suspension import (
    SuspensionError,
    SuspensionReasonCode,
    UserSuspension,
    create_suspension,
    lift_suspension as domain_lift,
)
from zeo_common import ApiError
from zeo_common.audit import AuditEntry, AuditWriter
from zeo_common.gateway import TokenVersionPublisher

logger = logging.getLogger("admin.service")


class AdminService:
    def __init__(
        self,
        repo: AdminRepository,
        audit_writer: AuditWriter,
        token_publisher: TokenVersionPublisher | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.audit = audit_writer
        self.token_publisher = token_publisher
        self.clock = clock

    async def suspend_user(
        self,
        admin_id: UUID,
        user_id: UUID,
        reason_code: str,
        note: str | None,
    ) -> UserSuspension:
        active = await self.repo.get_active_suspension(user_id)
        if active is not None:
            raise ApiError("CONFLICT", f"User {user_id} is already suspended", 409)

        now = self.clock()
        try:
            suspension = create_suspension(
                user_id=user_id,
                suspended_by=admin_id,
                reason_code=reason_code,
                note=note,
                now=now,
            )
        except ValueError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc), 422) from exc

        saved = await self.repo.save_suspension(suspension)

        # Force token refresh across the gateway
        if self.token_publisher:
            await self.token_publisher.bump_version(user_id)

        # Record in audit log
        await self.audit.write(
            AuditEntry(
                actor_id=admin_id,
                actor_role="ADMIN",
                service="admin-moderation",
                action="USER_SUSPEND",
                target_type="user",
                target_id=user_id,
                reason_code=str(suspension.reason_code),
                note=note,
                after_state={"suspended": True, "reason_code": str(suspension.reason_code)},
                at=now,
            )
        )
        logger.info("User %s suspended by admin %s (reason: %s)", user_id, admin_id, reason_code)
        return saved

    async def reinstate_user(
        self,
        admin_id: UUID,
        user_id: UUID,
        note: str | None = None,
    ) -> UserSuspension:
        active = await self.repo.get_active_suspension(user_id)
        if active is None:
            raise ApiError("NOT_FOUND", f"User {user_id} is not currently suspended", 404)

        now = self.clock()
        try:
            lifted = domain_lift(active, lifted_by=admin_id, now=now)
        except SuspensionError as exc:
            raise ApiError("CONFLICT", str(exc), 409) from exc

        saved = await self.repo.update_suspension(lifted)

        if self.token_publisher:
            await self.token_publisher.bump_version(user_id)

        await self.audit.write(
            AuditEntry(
                actor_id=admin_id,
                actor_role="ADMIN",
                service="admin-moderation",
                action="USER_REINSTATE",
                target_type="user",
                target_id=user_id,
                note=note,
                before_state={"suspended": True},
                after_state={"suspended": False},
                at=now,
            )
        )
        logger.info("User %s reinstated by admin %s", user_id, admin_id)
        return saved

    async def report_listing(
        self,
        auction_id: UUID,
        reported_by: UUID | None,
        reason: str | None,
        source: str = "USER_REPORT",
    ) -> ListingReview:
        now = self.clock()
        review = domain_create_review(
            auction_id=auction_id,
            source=source,
            now=now,
            reported_by=reported_by,
            reason=reason,
        )
        return await self.repo.save_review(review)

    async def list_pending_reviews(self) -> list[ListingReview]:
        return await self.repo.list_pending_reviews()

    async def approve_listing(
        self,
        admin_id: UUID,
        review_id: UUID,
        note: str | None = None,
    ) -> ListingReview:
        review = await self.repo.get_review(review_id)
        if review is None:
            raise ApiError("NOT_FOUND", f"Listing review {review_id} not found", 404)

        now = self.clock()
        approved = domain_approve(review, admin_id, now)
        saved = await self.repo.update_review(approved)

        await self.audit.write(
            AuditEntry(
                actor_id=admin_id,
                actor_role="ADMIN",
                service="admin-moderation",
                action="LISTING_APPROVE",
                target_type="auction",
                target_id=review.auction_id,
                note=note,
                before_state={"review_state": review.state.value},
                after_state={"review_state": saved.state.value},
                at=now,
            )
        )
        return saved

    async def remove_listing(
        self,
        admin_id: UUID,
        review_id: UUID,
        reason: str | None = None,
        note: str | None = None,
    ) -> ListingReview:
        review = await self.repo.get_review(review_id)
        if review is None:
            raise ApiError("NOT_FOUND", f"Listing review {review_id} not found", 404)

        now = self.clock()
        removed = domain_remove(review, admin_id, now)
        saved = await self.repo.update_review(removed)

        await self.audit.write(
            AuditEntry(
                actor_id=admin_id,
                actor_role="ADMIN",
                service="admin-moderation",
                action="LISTING_REMOVE",
                target_type="auction",
                target_id=review.auction_id,
                reason_code=reason,
                note=note,
                before_state={"review_state": review.state.value},
                after_state={"review_state": saved.state.value},
                at=now,
            )
        )
        return saved

    async def create_broadcast(
        self,
        admin_id: UUID,
        title: str,
        body: str,
    ) -> Broadcast:
        now = self.clock()
        broadcast = Broadcast(
            id=uuid4(),
            title=title,
            body=body,
            created_by=admin_id,
            created_at=now,
        )
        saved = await self.repo.save_broadcast(broadcast)
        await self.audit.write(
            AuditEntry(
                actor_id=admin_id,
                actor_role="ADMIN",
                service="admin-moderation",
                action="ADMIN_BROADCAST",
                target_type="broadcast",
                target_id=saved.id,
                note=title,
                at=now,
            )
        )
        return saved

    async def get_audit_log(
        self,
        *,
        target_type: str | None = None,
        target_id: UUID | None = None,
        actor_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.repo.get_audit_log(
            target_type=target_type,
            target_id=target_id,
            actor_id=actor_id,
            limit=limit,
            offset=offset,
        )

    async def get_daily_metrics(self) -> dict[str, Any]:
        """Summary metrics for admin dashboard."""
        pending_reviews = len(await self.repo.list_pending_reviews())
        return {
            "pending_listing_reviews": pending_reviews,
            "active_suspensions": len([s for s in getattr(self.repo, "suspensions", {}).values() if s.is_active]),
            "timestamp": self.clock().isoformat(),
        }
