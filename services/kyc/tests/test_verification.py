from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.submission import Submission
from app.domain.verification import (
    STATES,
    TRANSITIONS,
    IllegalTransition,
    ReasonRequired,
    can_submit,
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
    [("startReview", None), ("approve", None), ("reject", "Unreadable ID photograph."),
     ("suspend", "DOCUMENT_FORGERY"), ("reinstate", None)],
)
def test_every_table_row_is_accepted_from_its_from_state(event, reason):
    from_state, to_state = TRANSITIONS[event]
    transition, updated = plan_transition(submission(from_state), event, actor_id=ADMIN,
                                          reason=reason, now=NOW)
    assert (transition.from_state, transition.to_state, updated.state) == (
        from_state, to_state, to_state)
    assert transition.by_admin
    assert transition.audit_action.startswith("KYC_")


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("event", ["startReview", "approve", "reject", "suspend", "reinstate"])
def test_everything_else_is_refused(state, event):
    if TRANSITIONS[event][0] == state:
        return
    with pytest.raises(IllegalTransition):
        plan_transition(submission(state), event, actor_id=ADMIN, reason="DOCUMENT_FORGERY",
                        now=NOW)


def test_submit_and_unknown_events_cannot_be_planned():
    for event in ("submit", "teleport"):
        with pytest.raises(IllegalTransition):
            plan_transition(submission("SUBMITTED"), event, actor_id=ADMIN, reason=None, now=NOW)


def test_decisions_are_stamped():
    _, approved = plan_transition(submission("UNDER_REVIEW"), "approve", actor_id=ADMIN,
                                  reason=None, now=NOW)
    assert (approved.decided_at, approved.decided_by) == (NOW, ADMIN)
    _, reviewing = plan_transition(submission("SUBMITTED"), "startReview", actor_id=ADMIN,
                                   reason=None, now=NOW)
    assert reviewing.decided_by is None


@pytest.mark.parametrize(("event", "reason"), [("reject", "too short"), ("reject", None),
                                               ("suspend", "lowercase"), ("suspend", None)])
def test_reasons_are_required(event, reason):
    with pytest.raises(ReasonRequired):
        plan_transition(submission(TRANSITIONS[event][0]), event, actor_id=ADMIN,
                        reason=reason, now=NOW)


def test_only_a_rejection_reopens_submission():
    assert can_submit(None)
    assert can_submit(submission("REJECTED"))
    for state in ("SUBMITTED", "UNDER_REVIEW", "VERIFIED", "SUSPENDED"):
        assert not can_submit(submission(state))
