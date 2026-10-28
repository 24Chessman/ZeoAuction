"""Listing moderation queue domain logic (#81, Plan 6).

Sources:
    NEW_LISTING, USER_REPORT

States:
    PENDING, APPROVED, REMOVED
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ReviewSource(StrEnum):
    NEW_LISTING = "NEW_LISTING"
    USER_REPORT = "USER_REPORT"


class ReviewState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REMOVED = "REMOVED"


class ListingReviewError(Exception):
    pass


@dataclass(frozen=True)
class ListingReview:
    id: UUID
    auction_id: UUID
    source: ReviewSource
    state: ReviewState = ReviewState.PENDING
    reported_by: UUID | None = None
    reason: str | None = None
    reviewed_by: UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime | None = None


def create_review(
    auction_id: UUID,
    source: ReviewSource | str,
    now: datetime,
    *,
    reported_by: UUID | None = None,
    reason: str | None = None,
) -> ListingReview:
    return ListingReview(
        id=uuid4(),
        auction_id=auction_id,
        source=ReviewSource(source),
        state=ReviewState.PENDING,
        reported_by=reported_by,
        reason=reason,
        created_at=now,
    )


def approve_listing(
    review: ListingReview,
    admin_id: UUID,
    now: datetime,
) -> ListingReview:
    if review.state != ReviewState.PENDING:
        raise ListingReviewError(f"Cannot approve review in state {review.state}")
    return replace(review, state=ReviewState.APPROVED, reviewed_by=admin_id, decided_at=now)


def remove_listing(
    review: ListingReview,
    admin_id: UUID,
    now: datetime,
) -> ListingReview:
    if review.state != ReviewState.PENDING:
        raise ListingReviewError(f"Cannot remove listing in state {review.state}")
    return replace(review, state=ReviewState.REMOVED, reviewed_by=admin_id, decided_at=now)
