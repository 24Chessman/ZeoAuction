from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.submission import Submission
from app.domain.verification import (
    ADMIN_EVENTS,
    FACE_FAIL_REASON,
    STATES,
    TRANSITIONS,
    WITHDRAW_REASON,
    IllegalTransition,
    ReasonRequired,
    plan_transition,
)
from zeo_common.auth import KYC_STATUSES
from zeo_common.contract_testing import contract_schema

NOW = datetime(2026, 9, 10, tzinfo=UTC)
ADMIN = uuid4()


def submission(state: str) -> Submission:
    return Submission(id=uuid4(), user_id=uuid4(), state=state, rejection_reason=None,
                      submitted_at=NOW, decided_at=None, decided_by=None, updated_at=NOW)


def test_states_match_the_token_claim_vocabulary():
    # The mirror writes these into auth.users.kyc_status, which tokens carry as a claim.
    assert set(STATES) | {"NOT_SUBMITTED"} == set(KYC_STATUSES)


def test_states_match_the_published_ct2_vocabulary():
    published = contract_schema("openapi/internal/kyc-status.v1.yaml",
                                "/components/schemas/KycStatus")["enum"]
    assert set(published) == set(STATES) | {"NOT_SUBMITTED"}


@pytest.mark.parametrize(
    ("event", "reason"),
    [("approve", None), ("reject", "The live capture shows a different person."),
     ("suspend", "IDENTITY_MISMATCH"), ("reinstate", None)],
)
def test_every_admin_row_is_accepted_from_its_from_state(event, reason):
    from_state, to_state = TRANSITIONS[event]
    transition, updated = plan_transition(submission(from_state), event, actor_id=ADMIN,
                                          reason=reason, now=NOW)
    assert (transition.from_state, transition.to_state, updated.state) == (
        from_state, to_state, to_state)
    assert transition.by_admin
    assert transition.audit_action.startswith("KYC_")


@pytest.mark.parametrize(
    ("event", "to_state"),
    [("faceMatch", "UNDER_REVIEW"), ("faceReview", "UNDER_REVIEW"), ("faceFail", "REJECTED"),
     ("withdraw", "REJECTED")],
)
def test_face_check_and_seller_events_leave_submitted_without_an_audit_row(event, to_state):
    seller = uuid4()
    transition, updated = plan_transition(submission("SUBMITTED"), event, actor_id=seller,
                                          reason="face check NO_MATCH", now=NOW)
    assert (transition.from_state, updated.state) == ("SUBMITTED", to_state)
    assert not transition.by_admin
    assert transition.audit_action is None
    assert updated.decided_by is None  # decided_by names an administrator only


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("event", sorted(set(TRANSITIONS) - {"submit"}))
def test_everything_else_is_refused(state, event):
    if TRANSITIONS[event][0] == state:
        return
    with pytest.raises(IllegalTransition):
        plan_transition(submission(state), event, actor_id=ADMIN, reason="IDENTITY_MISMATCH",
                        now=NOW)


def test_submit_and_unknown_events_cannot_be_planned():
    for event in ("submit", "startReview", "teleport"):
        with pytest.raises(IllegalTransition):
            plan_transition(submission("SUBMITTED"), event, actor_id=ADMIN, reason=None, now=NOW)


def test_decisions_are_stamped():
    _, approved = plan_transition(submission("UNDER_REVIEW"), "approve", actor_id=ADMIN,
                                  reason=None, now=NOW)
    assert (approved.decided_at, approved.decided_by) == (NOW, ADMIN)
    _, matched = plan_transition(submission("SUBMITTED"), "faceMatch", actor_id=uuid4(),
                                 reason=None, now=NOW)
    assert (matched.decided_at, matched.decided_by) == (None, None)  # an admin still decides
    _, reviewing = plan_transition(submission("SUBMITTED"), "faceReview", actor_id=uuid4(),
                                   reason=None, now=NOW)
    assert (reviewing.decided_at, reviewing.decided_by) == (None, None)


def test_system_rejections_always_carry_a_reason():
    # REJECTED rows need a rejection_reason (CHECK in 20-kyc.sql).
    _, failed = plan_transition(submission("SUBMITTED"), "faceFail", actor_id=uuid4(),
                                reason=None, now=NOW)
    assert failed.rejection_reason == FACE_FAIL_REASON
    _, withdrawn = plan_transition(submission("SUBMITTED"), "withdraw", actor_id=uuid4(),
                                   reason="ignored", now=NOW)
    assert withdrawn.rejection_reason == WITHDRAW_REASON


@pytest.mark.parametrize(("event", "reason"), [("reject", "too short"), ("reject", None),
                                               ("suspend", "lowercase"), ("suspend", None)])
def test_reasons_are_required(event, reason):
    with pytest.raises(ReasonRequired):
        plan_transition(submission(TRANSITIONS[event][0]), event, actor_id=ADMIN,
                        reason=reason, now=NOW)


def test_admins_cannot_trigger_face_check_events():
    assert ADMIN_EVENTS == {"approve", "reject", "suspend", "reinstate"}
