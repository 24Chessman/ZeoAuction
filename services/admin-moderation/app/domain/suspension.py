"""User suspension domain logic (#82, Plan 6).

Reason codes:
    SHILL_BIDDING, FRAUD, ABUSIVE_BEHAVIOR, NON_PAYMENT, TERMS_VIOLATION, OTHER
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class SuspensionReasonCode(StrEnum):
    SHILL_BIDDING = "SHILL_BIDDING"
    FRAUD = "FRAUD"
    ABUSIVE_BEHAVIOR = "ABUSIVE_BEHAVIOR"
    NON_PAYMENT = "NON_PAYMENT"
    TERMS_VIOLATION = "TERMS_VIOLATION"
    OTHER = "OTHER"


class SuspensionError(Exception):
    pass


@dataclass(frozen=True)
class UserSuspension:
    id: UUID
    user_id: UUID
    reason_code: SuspensionReasonCode
    suspended_by: UUID
    suspended_at: datetime
    note: str | None = None
    lifted_by: UUID | None = None
    lifted_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.lifted_at is None


def create_suspension(
    user_id: UUID,
    suspended_by: UUID,
    reason_code: SuspensionReasonCode | str,
    note: str | None,
    now: datetime,
) -> UserSuspension:
    return UserSuspension(
        id=uuid4(),
        user_id=user_id,
        reason_code=SuspensionReasonCode(reason_code),
        note=note,
        suspended_by=suspended_by,
        suspended_at=now,
    )


def lift_suspension(
    suspension: UserSuspension,
    lifted_by: UUID,
    now: datetime,
) -> UserSuspension:
    if not suspension.is_active:
        raise SuspensionError("Suspension is already lifted")
    return replace(suspension, lifted_by=lifted_by, lifted_at=now)
