"""Dispute lifecycle state machine and domain logic (#84; docs/state-machines.md section 4).

Dispute states:
    OPEN -> UNDER_REVIEW -> RESOLVED_SELLER / RESOLVED_BUYER

Reason codes:
    ITEM_NOT_RECEIVED, NOT_AS_DESCRIBED, DAMAGED_IN_TRANSIT, COUNTERFEIT, SUSPECTED_FRAUD, OTHER

Faults:
    BUYER, SELLER, PLATFORM (drives fee treatment on refund, SDD Table 6.3)

Evidence kinds:
    PHOTO, DOCUMENT, BID_TRACE, SELLER_RESPONSE
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class DisputeState(StrEnum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_SELLER = "RESOLVED_SELLER"
    RESOLVED_BUYER = "RESOLVED_BUYER"


class ReasonCode(StrEnum):
    ITEM_NOT_RECEIVED = "ITEM_NOT_RECEIVED"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    DAMAGED_IN_TRANSIT = "DAMAGED_IN_TRANSIT"
    COUNTERFEIT = "COUNTERFEIT"
    SUSPECTED_FRAUD = "SUSPECTED_FRAUD"
    OTHER = "OTHER"


class Fault(StrEnum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    PLATFORM = "PLATFORM"


class EvidenceKind(StrEnum):
    PHOTO = "PHOTO"
    DOCUMENT = "DOCUMENT"
    BID_TRACE = "BID_TRACE"
    SELLER_RESPONSE = "SELLER_RESPONSE"


class OpenedBy(StrEnum):
    BUYER = "BUYER"
    FRAUD_SERVICE = "FRAUD_SERVICE"


class DisputeError(Exception):
    pass


class WindowClosedError(DisputeError):
    """Refused with WINDOW_CLOSED (409) when window has passed (AC-11)."""


class DisputeConflictError(DisputeError):
    """An open or under-review dispute already exists for this order."""


@dataclass(frozen=True)
class Dispute:
    id: UUID
    order_id: UUID
    opened_by: OpenedBy
    reason_code: ReasonCode
    description: str
    state: DisputeState = DisputeState.OPEN
    opened_by_user_id: UUID | None = None
    fraud_alert_id: UUID | None = None
    fault: Fault | None = None
    resolution_note: str | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.opened_by == OpenedBy.BUYER and self.opened_by_user_id is None:
            raise DisputeError("Buyer-opened dispute must have opened_by_user_id")
        if self.opened_by == OpenedBy.FRAUD_SERVICE and self.fraud_alert_id is None:
            raise DisputeError("Fraud service-opened dispute must have fraud_alert_id")
        if self.state == DisputeState.RESOLVED_BUYER and self.fault is None:
            raise DisputeError("A dispute resolved in buyer's favour requires a fault")
        if self.state in (DisputeState.RESOLVED_SELLER, DisputeState.RESOLVED_BUYER) and self.resolved_at is None:
            raise DisputeError("Resolved dispute must have resolved_at")


@dataclass(frozen=True)
class DisputeEvidence:
    id: UUID
    dispute_id: UUID
    kind: EvidenceKind
    submitted_by: UUID | None = None
    object_key: str | None = None
    bid_trace: dict[str, Any] | None = None
    body: str | None = None
    submitted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.kind in (EvidenceKind.PHOTO, EvidenceKind.DOCUMENT) and not self.object_key:
            raise DisputeError("PHOTO and DOCUMENT evidence require an object_key")
        if self.kind == EvidenceKind.BID_TRACE and not self.bid_trace:
            raise DisputeError("BID_TRACE evidence requires bid_trace data")
        if self.kind == EvidenceKind.SELLER_RESPONSE and not self.body:
            raise DisputeError("SELLER_RESPONSE evidence requires a text body")


def create_buyer_dispute(
    order_id: UUID,
    user_id: UUID,
    reason_code: ReasonCode | str,
    description: str,
    now: datetime,
    protection_window_ends_at: datetime | None = None,
) -> Dispute:
    """Create a dispute opened by a buyer; refuses if window is expired (AC-11)."""
    if protection_window_ends_at is not None and now >= protection_window_ends_at:
        raise WindowClosedError(f"Protection window expired at {protection_window_ends_at}")

    return Dispute(
        id=uuid4(),
        order_id=order_id,
        opened_by=OpenedBy.BUYER,
        opened_by_user_id=user_id,
        reason_code=ReasonCode(reason_code),
        description=description,
        state=DisputeState.OPEN,
        opened_at=now,
        updated_at=now,
    )


def create_fraud_dispute(
    order_id: UUID,
    fraud_alert_id: UUID,
    description: str,
    now: datetime,
) -> Dispute:
    """Create a dispute opened by the fraud service."""
    return Dispute(
        id=uuid4(),
        order_id=order_id,
        opened_by=OpenedBy.FRAUD_SERVICE,
        fraud_alert_id=fraud_alert_id,
        reason_code=ReasonCode.SUSPECTED_FRAUD,
        description=description,
        state=DisputeState.OPEN,
        opened_at=now,
        updated_at=now,
    )


def start_review(dispute: Dispute, now: datetime) -> Dispute:
    """Move OPEN dispute to UNDER_REVIEW."""
    if dispute.state != DisputeState.OPEN:
        raise DisputeError(f"Cannot start review from state {dispute.state}")
    return replace(dispute, state=DisputeState.UNDER_REVIEW, updated_at=now)


def resolve_dispute(
    dispute: Dispute,
    outcome: DisputeState | str,
    fault: Fault | str | None,
    note: str,
    admin_id: UUID,
    now: datetime,
) -> Dispute:
    """Resolve dispute (RESOLVED_SELLER or RESOLVED_BUYER). Outcome and fault are separate."""
    outcome_val = DisputeState(outcome) if isinstance(outcome, str) else outcome
    fault_val = Fault(fault) if fault is not None and isinstance(fault, str) else fault

    if outcome_val not in (DisputeState.RESOLVED_SELLER, DisputeState.RESOLVED_BUYER):
        raise DisputeError(f"Invalid resolution outcome: {outcome}")

    if outcome_val == DisputeState.RESOLVED_BUYER and fault_val is None:
        raise DisputeError("Resolving in buyer favour requires a fault (BUYER, SELLER, PLATFORM)")

    return replace(
        dispute,
        state=outcome_val,
        fault=fault_val,
        resolution_note=note,
        resolved_by=admin_id,
        resolved_at=now,
        updated_at=now,
    )
