"""Seller verification state machine, transitions K1-K7 (#40; docs/state-machines.md section 3).

Pure logic, no I/O. Every accepted transition is recorded in ``kyc_state_transitions`` with
its actor, mirrored to ``auth.users.kyc_status`` with a ``token_version`` bump (which forces
the seller's next request through a gate to refresh its token), and, when an administrator
made it, written to ``admin.audit_log``. Anything not in :data:`TRANSITIONS` is refused.

REJECTED is recoverable (a new submission, K5) and SUSPENDED is reversible (K7).
"""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from app.domain.submission import Submission

STATES = ("SUBMITTED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "SUSPENDED")

# event -> (from_state, to_state). "submit" creates a row, so it has no from-state; K5
# (resubmit after REJECTED) is a "submit" of a new row, the old row is kept for audit.
TRANSITIONS: dict[str, tuple[str | None, str]] = {
    "submit": (None, "SUBMITTED"),            # K1, K5
    "startReview": ("SUBMITTED", "UNDER_REVIEW"),  # K2
    "approve": ("UNDER_REVIEW", "VERIFIED"),  # K3
    "reject": ("UNDER_REVIEW", "REJECTED"),   # K4
    "suspend": ("VERIFIED", "SUSPENDED"),     # K6
    "reinstate": ("SUSPENDED", "VERIFIED"),   # K7
}
ADMIN_EVENTS = frozenset({"startReview", "approve", "reject", "suspend", "reinstate"})

# admin.audit_log action names (SDD 8.8).
AUDIT_ACTIONS = {
    "startReview": "KYC_START_REVIEW",
    "approve": "KYC_APPROVE",
    "reject": "KYC_REJECT",
    "suspend": "KYC_SUSPEND",
    "reinstate": "KYC_REINSTATE",
}
DOC_VIEW_ACTION = "KYC_DOC_VIEW"

REJECT_REASON_LENGTH = (10, 500)
REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")


class IllegalTransition(Exception):
    def __init__(self, event: str, state: str | None) -> None:
        super().__init__(f"event {event!r} is not allowed from state {state}")
        self.event = event
        self.state = state


class ReasonRequired(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    """One accepted transition, everything the repository writes in its transaction."""

    submission_id: UUID
    user_id: UUID
    event: str
    from_state: str | None
    to_state: str
    actor_id: UUID
    reason: str | None
    at: datetime

    @property
    def by_admin(self) -> bool:
        return self.event in ADMIN_EVENTS

    @property
    def audit_action(self) -> str | None:
        return AUDIT_ACTIONS.get(self.event)


def check_reason(event: str, reason: str | None) -> str | None:
    if event == "reject":
        text = (reason or "").strip()
        low, high = REJECT_REASON_LENGTH
        if not low <= len(text) <= high:
            raise ReasonRequired(f"A rejection reason of {low} to {high} characters is required")
        return text
    if event == "suspend":
        if not reason or not REASON_CODE.match(reason):
            raise ReasonRequired("A reason code such as DOCUMENT_FORGERY is required")
        return reason
    return None


def plan_transition(
    submission: Submission, event: str, *, actor_id: UUID, reason: str | None, now: datetime
) -> tuple[Transition, Submission]:
    """Check ``event`` against the table and return the record plus the updated row."""
    if event not in TRANSITIONS or event == "submit":
        raise IllegalTransition(event, submission.state)
    from_state, to_state = TRANSITIONS[event]
    if submission.state != from_state:
        raise IllegalTransition(event, submission.state)
    reason = check_reason(event, reason)
    transition = Transition(
        submission_id=submission.id, user_id=submission.user_id, event=event,
        from_state=from_state, to_state=to_state, actor_id=actor_id, reason=reason, at=now,
    )
    decided = event in ("approve", "reject")
    updated = replace(
        submission,
        state=to_state,
        rejection_reason=reason if event == "reject" else submission.rejection_reason,
        decided_at=now if decided else submission.decided_at,
        decided_by=actor_id if decided else submission.decided_by,
        updated_at=now,
    )
    return transition, updated


def can_submit(latest: Submission | None) -> bool:
    """K1 (no submission yet) or K5 (the latest one was rejected)."""
    return latest is None or latest.state == "REJECTED"


def submit_transition(submission: Submission, now: datetime,
                      previous: Submission | None) -> Transition:
    reason = None if previous is None else f"resubmission after {previous.id}"
    return Transition(
        submission_id=submission.id, user_id=submission.user_id, event="submit",
        from_state=None, to_state="SUBMITTED", actor_id=submission.user_id, reason=reason, at=now,
    )
