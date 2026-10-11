from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from tests.support import bearer


def test_admin_routes_need_the_admin_role(harness):
    _, submission_id = harness.submitted()
    response = harness.client.post(f"/api/v1/admin/kyc/{submission_id}/approve",
                                   headers=bearer(uuid4()))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_queue_lists_waiting_submissions_oldest_first(harness):
    ids = [harness.submitted()[1] for _ in range(3)]
    harness.admin_post(f"{ids[1]}/start-review")
    page = harness.admin_get("queue").json()
    assert [item["submission_id"] for item in page["items"]] == ids
    only_new = harness.admin_get("queue", state="SUBMITTED").json()
    assert [item["submission_id"] for item in only_new["items"]] == [ids[0], ids[2]]
    second = harness.admin_get("queue", limit=1, offset=1).json()
    assert [item["submission_id"] for item in second["items"]] == [ids[1]]


def test_full_approval_flow_mirrors_verified_and_audits(harness):
    user, submission_id = harness.submitted()
    review = harness.admin_post(f"{submission_id}/start-review")
    assert review.json()["state"] == "UNDER_REVIEW"
    approved = harness.admin_post(f"{submission_id}/approve")
    assert approved.status_code == 200
    body = approved.json()
    assert body["state"] == "VERIFIED"
    assert body["decided_by"] == str(harness.admin)
    assert harness.repo.mirror.users[user] == ("VERIFIED", 4)
    assert harness.versions.versions[user] == 4  # the seller's old token is now stale
    actions = [row[3] for row in harness.repo.audit_log]
    assert actions == ["KYC_START_REVIEW", "KYC_APPROVE"]
    assert [t.event for t in harness.repo.transitions] == ["submit", "startReview", "approve"]
    assert all(t.actor_id == harness.admin for t in harness.repo.transitions[1:])


def test_approving_without_review_is_an_illegal_transition(harness):
    user, submission_id = harness.submitted()
    response = harness.admin_post(f"{submission_id}/approve")
    assert response.status_code == 409
    assert response.json()["details"] == {"state": "SUBMITTED", "event": "approve"}
    assert harness.repo.mirror.users[user] == ("SUBMITTED", 2)
    assert harness.repo.audit_log == []


def test_reject_requires_a_reason(harness):
    _, submission_id = harness.submitted()
    harness.admin_post(f"{submission_id}/start-review")
    assert harness.admin_post(f"{submission_id}/reject", {"reason": "bad"}).status_code == 422
    assert harness.admin_post(f"{submission_id}/reject", {}).status_code == 422
    response = harness.admin_post(f"{submission_id}/reject",
                                  {"reason": "Address proof is older than three months."})
    assert response.status_code == 200
    assert response.json()["rejection_reason"] == "Address proof is older than three months."
    assert harness.repo.audit_log[-1][9] == "Address proof is older than three months."


def test_suspend_and_reinstate(harness):
    user, submission_id = harness.submitted()
    harness.admin_post(f"{submission_id}/start-review")
    harness.admin_post(f"{submission_id}/approve")
    assert harness.admin_post(f"{submission_id}/suspend",
                              {"reason_code": "bad code"}).status_code == 422
    suspended = harness.admin_post(f"{submission_id}/suspend",
                                   {"reason_code": "DOCUMENT_FORGERY"})
    assert suspended.json()["state"] == "SUSPENDED"
    assert harness.repo.mirror.users[user][0] == "SUSPENDED"
    assert harness.repo.audit_log[-1][8] == "DOCUMENT_FORGERY"
    reinstated = harness.admin_post(f"{submission_id}/reinstate")
    assert reinstated.json()["state"] == "VERIFIED"
    assert harness.repo.mirror.users[user][0] == "VERIFIED"


def test_terminal_like_states_refuse_review_actions(harness):
    _, submission_id = harness.submitted()
    harness.admin_post(f"{submission_id}/start-review")
    harness.admin_post(f"{submission_id}/approve")
    for action in ("start-review", "approve"):
        assert harness.admin_post(f"{submission_id}/{action}").status_code == 409
    assert harness.admin_post(f"{submission_id}/reject",
                              {"reason": "Too late to reject this one."}).status_code == 409


def test_unknown_submission_is_not_found(harness):
    assert harness.admin_post(f"{uuid4()}/approve").status_code == 404
    assert harness.admin_get(str(uuid4())).status_code == 404


def test_detail_shows_document_metadata_without_urls(harness):
    _, submission_id = harness.submitted()
    body = harness.admin_get(submission_id).json()
    assert len(body["documents"]) == 2
    assert all(len(doc["sha256"]) == 64 for doc in body["documents"])
    assert "url" not in body["documents"][0]


def test_document_view_is_a_short_lived_signed_url_and_is_audited(harness):
    _, submission_id = harness.submitted()
    document = harness.admin_get(submission_id).json()["documents"][0]
    response = harness.admin_get(f"{submission_id}/documents/{document['document_id']}/url")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["expires_in"] == 60
    query = parse_qs(urlsplit(body["url"]).query)
    assert query["X-Amz-Expires"] == ["60"]
    assert "X-Amz-Signature" in query
    (view,) = harness.repo.audit_log
    assert view[3] == "KYC_DOC_VIEW"
    assert str(view[5]) == document["document_id"]


def test_document_of_another_submission_is_not_found(harness):
    _, first = harness.submitted()
    _, second = harness.submitted()
    document = harness.admin_get(first).json()["documents"][0]
    response = harness.admin_get(f"{second}/documents/{document['document_id']}/url")
    assert response.status_code == 404
    assert harness.repo.audit_log == []


def test_a_racing_admin_gets_a_conflict(harness, monkeypatch):
    from app.adapters.kyc_repo import StaleSubmission

    _, submission_id = harness.submitted()

    async def lost_race(*args):
        raise StaleSubmission(submission_id)

    monkeypatch.setattr(harness.repo, "apply", lost_race)
    response = harness.admin_post(f"{submission_id}/start-review")
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


async def test_in_memory_apply_refuses_a_row_that_moved(harness):
    from dataclasses import replace

    from app.adapters.kyc_repo import StaleSubmission
    from app.domain.verification import plan_transition

    _, submission_id = harness.submitted()
    row = next(iter(harness.repo.submissions.values()))
    transition, updated = plan_transition(row, "startReview", actor_id=harness.admin,
                                          reason=None, now=row.submitted_at)
    harness.repo.submissions[row.id] = replace(row, state="UNDER_REVIEW")
    with pytest.raises(StaleSubmission):
        await harness.repo.apply(transition, updated, "ADMIN", None)
