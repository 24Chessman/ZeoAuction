"""Seller verification state machine (docs/state-machines.md section 3).

Pure logic, no I/O. A submission starts when a seller's Aadhaar Secure QR verifies
(K1), then the live face check runs: a match, clear (K3a) or borderline (K2), puts the
submission in the administrator queue, and the last failed attempt rejects it (K4a). Only an
administrator verifies a seller (K3).
Re-uploading the QR before any counted face attempt withdraws the waiting row (K4b).

Every accepted transition is recorded in ``kyc_state_transitions`` with its actor, mirrored to
``auth.users.kyc_status`` with a ``token_version`` bump (which forces the seller's next request
through a gate to refresh its token), and, when an administrator made it, written to
``admin.audit_log``. Anything not in :data:`TRANSITIONS` is refused.

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
    "submit": (None, "SUBMITTED"),                # K1, K5: Secure QR verified
    "faceReview": ("SUBMITTED", "UNDER_REVIEW"),  # K2: borderline face match
    "faceMatch": ("SUBMITTED", "UNDER_REVIEW"),   # K3a: clear face match, still needs an admin
    "faceFail": ("SUBMITTED", "REJECTED"),        # K4a: last face attempt failed
    "withdraw": ("SUBMITTED", "REJECTED"),        # K4b: seller uploads a different QR
    "approve": ("UNDER_REVIEW", "VERIFIED"),      # K3
    "reject": ("UNDER_REVIEW", "REJECTED"),       # K4
    "suspend": ("VERIFIED", "SUSPENDED"),         # K6
    "reinstate": ("SUSPENDED", "VERIFIED"),       # K7
}
ADMIN_EVENTS = frozenset({"approve", "reject", "suspend", "reinstate"})
SELLER_EVENTS = frozenset({"faceReview", "faceMatch", "faceFail", "withdraw"})
DECIDING_EVENTS = frozenset({"approve", "reject", "faceFail"})

# admin.audit_log action names (SDD 8.8).
AUDIT_ACTIONS = {
    "approve": "KYC_APPROVE",
    "reject": "KYC_REJECT",
    "suspend": "KYC_SUSPEND",
    "reinstate": "KYC_REINSTATE",
}
DOC_VIEW_ACTION = "KYC_DOC_VIEW"

REJECT_REASON_LENGTH = (10, 500)
REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")

FACE_FAIL_REASON = "The live face check did not match the Aadhaar photo"
WITHDRAW_REASON = "Replaced by a new Aadhaar QR upload"


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
            raise ReasonRequired("A reason code such as IDENTITY_MISMATCH is required")
        return reason
    if event == "faceFail":
        return reason or FACE_FAIL_REASON
    if event == "withdraw":
        return WITHDRAW_REASON
    return reason if event in SELLER_EVENTS else None


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
    decided = event in DECIDING_EVENTS or event == "withdraw"
    updated = replace(
        submission,
        state=to_state,
        rejection_reason=reason if to_state == "REJECTED" else submission.rejection_reason,
        decided_at=now if decided else submission.decided_at,
        # decided_by names an administrator; the face check decides on its own.
        decided_by=actor_id if decided and event in ADMIN_EVENTS else submission.decided_by,
        updated_at=now,
    )
    return transition, updated


def submit_transition(submission: Submission, now: datetime,
                      previous: Submission | None) -> Transition:
    reason = None if previous is None else f"resubmission after {previous.id}"
    return Transition(
        submission_id=submission.id, user_id=submission.user_id, event="submit",
        from_state=None, to_state="SUBMITTED", actor_id=submission.user_id, reason=reason, at=now,
    )
