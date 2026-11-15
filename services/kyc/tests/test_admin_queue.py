from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from tests.support import bearer


def test_admin_routes_need_the_admin_role(harness):
    _, submission_id = harness.in_review()
    response = harness.client.post(f"/api/v1/admin/kyc/{submission_id}/approve",
                                   headers=bearer(uuid4()))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_the_queue_holds_aadhaar_submissions_oldest_first(harness):
    reviewing = [harness.in_review()[1] for _ in range(2)]
    waiting = harness.submitted()[1]
    page = harness.admin_get("queue").json()
    assert [item["submission_id"] for item in page["items"]] == reviewing + [waiting]
    assert all(item["state"] == "UNDER_REVIEW" for item in page["items"])
    second = harness.admin_get("queue", limit=1, offset=1).json()
    assert [item["submission_id"] for item in second["items"]] == [reviewing[1]]


def test_approving_a_referral_mirrors_verified_and_audits(harness):
    user, submission_id = harness.in_review()
    approved = harness.admin_post(f"{submission_id}/approve")
    assert approved.status_code == 200
    body = approved.json()
    assert body["state"] == "VERIFIED"
    assert body["decided_by"] == str(harness.admin)
    assert harness.repo.mirror.users[user] == ("VERIFIED", 3)
    assert harness.versions.versions[user] == 3  # the seller's old token is now stale
    assert [row[3] for row in harness.repo.audit_log] == ["KYC_APPROVE"]
    assert [t.event for t in harness.repo.transitions] == ["submit", "approve"]
    assert harness.repo.transitions[-1].actor_id == harness.admin


def test_the_start_review_route_is_gone(harness):
    _, submission_id = harness.submitted()
    assert harness.admin_post(f"{submission_id}/start-review").status_code in (404, 405)


def test_reject_requires_a_reason(harness):
    _, submission_id = harness.in_review()
    assert harness.admin_post(f"{submission_id}/reject", {"reason": "bad"}).status_code == 422
    assert harness.admin_post(f"{submission_id}/reject", {}).status_code == 422
    reason = "The Aadhaar QR could not be accepted."
    response = harness.admin_post(f"{submission_id}/reject", {"reason": reason})
    assert response.status_code == 200
    assert response.json()["rejection_reason"] == reason
    assert harness.repo.audit_log[-1][9] == reason


def test_an_admin_rejection_allows_a_new_upload_at_once(harness):
    user, submission_id = harness.in_review()
    harness.admin_post(f"{submission_id}/reject", {"reason": "Photo too blurry to compare."})
    assert harness.me(user).json()["can_resubmit"] is True
    assert harness.upload(user).status_code == 201


def test_suspend_and_reinstate(harness):
    user, submission_id = harness.submitted()
    assert harness.repo.mirror.users[user][0] == "UNDER_REVIEW"
    assert harness.admin_post(f"{submission_id}/approve").json()["state"] == "VERIFIED"
    assert harness.admin_post(f"{submission_id}/suspend",
                              {"reason_code": "bad code"}).status_code == 422
    suspended = harness.admin_post(f"{submission_id}/suspend",
                                   {"reason_code": "IDENTITY_MISMATCH"})
    assert suspended.json()["state"] == "SUSPENDED"
    assert harness.repo.mirror.users[user][0] == "SUSPENDED"
    assert harness.repo.audit_log[-1][8] == "IDENTITY_MISMATCH"
    reinstated = harness.admin_post(f"{submission_id}/reinstate")
    assert reinstated.json()["state"] == "VERIFIED"
    assert harness.repo.mirror.users[user][0] == "VERIFIED"


def test_verified_submissions_refuse_review_actions(harness):
    _, submission_id = harness.in_review()
    harness.admin_post(f"{submission_id}/approve")
    assert harness.admin_post(f"{submission_id}/approve").status_code == 409
    assert harness.admin_post(f"{submission_id}/reject",
                              {"reason": "Too late to reject this one."}).status_code == 409


def test_unknown_submission_is_not_found(harness):
    assert harness.admin_post(f"{uuid4()}/approve").status_code == 404
    assert harness.admin_get(str(uuid4())).status_code == 404


def test_detail_shows_the_aadhaar_summary_and_every_attempt(harness):
    _, submission_id = harness.in_review()
    body = harness.admin_get(submission_id).json()
    assert body["aadhaar"]["holder_name"] == "Asha Verma"
    assert body["aadhaar"]["pincode"] == "411001"
    assert body["aadhaar"]["face_model"] == "disabled"
    assert body["aadhaar"]["reference_faces"] == 0
    assert len(body["aadhaar"]["signer_sha256"]) == 64
    assert "reference_embedding" not in body["aadhaar"]
    assert body["face_attempts"] == []
    assert {d["doc_type"] for d in body["documents"]} == {"AADHAAR_PHOTO"}
    assert all(len(doc["sha256"]) == 64 for doc in body["documents"])
    assert "url" not in body["documents"][0]


def test_document_view_is_a_short_lived_signed_url_and_is_audited(harness):
    _, submission_id = harness.in_review()
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

    _, submission_id = harness.in_review()

    async def lost_race(*args):
        raise StaleSubmission(submission_id)

    monkeypatch.setattr(harness.repo, "apply", lost_race)
    response = harness.admin_post(f"{submission_id}/approve")
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_a_deleted_account_is_a_conflict(harness, monkeypatch):
    from app.adapters.user_mirror import UnknownUser

    _, submission_id = harness.in_review()

    async def gone(*args):
        raise UnknownUser("deleted")

    monkeypatch.setattr(harness.repo, "apply", gone)
    assert harness.admin_post(f"{submission_id}/approve").status_code == 409


async def test_in_memory_apply_refuses_a_row_that_moved(harness):
    from dataclasses import replace

    from app.adapters.kyc_repo import StaleSubmission
    from app.domain.verification import plan_transition

    _, submission_id = harness.in_review()
    row = next(iter(harness.repo.submissions.values()))
    transition, updated = plan_transition(row, "approve", actor_id=harness.admin,
                                          reason=None, now=row.submitted_at)
    harness.repo.submissions[row.id] = replace(row, state="VERIFIED")
    with pytest.raises(StaleSubmission):
        await harness.repo.apply(transition, updated, "ADMIN", None)
