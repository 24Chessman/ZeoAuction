from uuid import UUID, uuid4

import pytest

from tests.support import JPEG, PDF, PNG, bearer
from zeo_common.contract_testing import assert_matches_contract


def test_submission_creates_a_submitted_row_with_documents(harness):
    user = uuid4()
    response = harness.submit(user)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "SUBMITTED"
    assert body["can_resubmit"] is False
    assert {d["doc_type"] for d in body["documents"]} == {"GOVERNMENT_ID", "PROOF_OF_ADDRESS"}
    assert "url" not in str(body).lower()


def test_documents_are_stored_under_id_only_keys(harness):
    user = uuid4()
    submission = harness.submit(user).json()
    keys = sorted(harness.store.objects)
    assert len(keys) == 2
    for key in keys:
        assert key.startswith(f"kyc/{user}/{submission['submission_id']}/")
        assert "id.pdf" not in key and "bill" not in key
    stored = {doc.object_key for doc in harness.repo.docs.values()}
    assert stored == set(keys)


def test_submit_mirrors_the_status_and_forces_a_token_refresh(harness):
    user = uuid4()
    harness.submit(user)
    assert harness.repo.mirror.users[user] == ("SUBMITTED", 2)
    assert harness.versions.versions[user] == 2
    (transition,) = harness.repo.transitions
    assert (transition.event, transition.from_state, transition.to_state) == (
        "submit", None, "SUBMITTED")
    assert transition.actor_id == user


def test_my_submission(harness):
    user = uuid4()
    harness.submit(user)
    response = harness.client.get("/api/v1/kyc/submissions/me", headers=bearer(user))
    assert response.status_code == 200
    assert response.json()["state"] == "SUBMITTED"


def test_my_submission_before_submitting_is_not_found(harness):
    response = harness.client.get("/api/v1/kyc/submissions/me", headers=bearer(uuid4()))
    assert response.status_code == 404
    assert response.json()["details"] == {"kyc_status": "NOT_SUBMITTED"}
    assert_matches_contract(response.json(), "openapi/common.v1.yaml",
                            "/components/schemas/Error")


def test_a_second_live_submission_is_refused(harness):
    user = uuid4()
    harness.submit(user)
    response = harness.submit(user)
    assert response.status_code == 409
    assert response.json()["code"] == "KYC_ALREADY_ACTIVE"
    assert response.json()["details"] == {"state": "SUBMITTED"}
    assert len(harness.store.objects) == 2  # nothing stored for the refused attempt


def test_submissions_require_a_token(harness):
    response = harness.client.post("/api/v1/kyc/submissions",
                                   files={"government_id": ("a.pdf", PDF, "application/pdf")})
    assert response.status_code == 401


def test_a_missing_required_document_is_a_validation_error(harness):
    response = harness.submit(uuid4(), government_id=("id.pdf", PDF, "application/pdf"))
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("government_id", "reason"),
    [
        (("id.exe", b"MZ\x90\x00binary", "application/pdf"), "unsupported_format"),
        (("id.pdf", PDF, "image/png"), "mime_mismatch"),
        (("id.pdf", b"%PDF-" + b"x" * 2000, "application/pdf"), "too_large"),
        (("id.pdf", b"", "application/pdf"), "empty"),
    ],
)
def test_invalid_documents_are_refused_before_anything_is_stored(harness, government_id, reason):
    response = harness.submit(
        uuid4(), government_id=government_id,
        proof_of_address=("bill.png", PNG, "image/png"),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "DOCUMENT_INVALID"
    assert body["details"] == {"doc_type": "GOVERNMENT_ID", "reason": reason}
    assert harness.store.objects == {}
    assert harness.repo.submissions == {}


def test_a_generic_content_type_is_resolved_by_sniffing(harness):
    response = harness.submit(
        uuid4(), government_id=("id", JPEG, "application/octet-stream"),
        proof_of_address=("bill", PDF, "application/pdf"),
    )
    assert response.status_code == 201
    types = {d["doc_type"]: d["mime_type"] for d in response.json()["documents"]}
    assert types["GOVERNMENT_ID"] == "image/jpeg"


def test_storage_failure_saves_nothing_and_is_retryable(harness):
    harness.store.fail_next_put = True
    response = harness.submit(uuid4())
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
    assert harness.repo.submissions == {}


def test_a_failed_commit_removes_the_stored_objects(harness, monkeypatch):
    async def boom(*args):
        raise RuntimeError("database down")

    monkeypatch.setattr(harness.repo, "create", boom)
    response = harness.submit(uuid4())
    assert response.status_code == 500
    assert harness.store.objects == {}


def test_optional_selfie_can_be_added_before_review(harness):
    user, submission_id = harness.submitted()
    response = harness.client.post(
        f"/api/v1/kyc/submissions/{submission_id}/documents",
        data={"doc_type": "SELFIE"}, files={"file": ("me.jpg", JPEG, "image/jpeg")},
        headers=bearer(user),
    )
    assert response.status_code == 201
    assert response.json()["doc_type"] == "SELFIE"
    assert len(harness.store.objects) == 3


def test_a_document_type_cannot_be_added_twice(harness):
    user, submission_id = harness.submitted()
    response = harness.client.post(
        f"/api/v1/kyc/submissions/{submission_id}/documents",
        data={"doc_type": "GOVERNMENT_ID"}, files={"file": ("id.pdf", PDF, "application/pdf")},
        headers=bearer(user),
    )
    assert response.status_code == 409
    assert len(harness.store.objects) == 2


def test_documents_cannot_be_added_to_someone_elses_submission(harness):
    _, submission_id = harness.submitted()
    response = harness.client.post(
        f"/api/v1/kyc/submissions/{submission_id}/documents",
        data={"doc_type": "SELFIE"}, files={"file": ("me.jpg", JPEG, "image/jpeg")},
        headers=bearer(uuid4()),
    )
    assert response.status_code == 404


def test_documents_cannot_be_added_once_review_started(harness):
    user, submission_id = harness.submitted()
    harness.admin_post(f"{submission_id}/start-review")
    response = harness.client.post(
        f"/api/v1/kyc/submissions/{submission_id}/documents",
        data={"doc_type": "SELFIE"}, files={"file": ("me.jpg", JPEG, "image/jpeg")},
        headers=bearer(user),
    )
    assert response.status_code == 409
    assert response.json()["details"] == {"state": "UNDER_REVIEW"}


def test_an_invalid_added_document_is_refused(harness):
    user, submission_id = harness.submitted()
    response = harness.client.post(
        f"/api/v1/kyc/submissions/{submission_id}/documents",
        data={"doc_type": "PASSPORT_SCAN"}, files={"file": ("x.pdf", PDF, "application/pdf")},
        headers=bearer(user),
    )
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "unknown_type"


def test_resubmission_after_rejection_creates_a_new_row(harness):
    user, first = harness.submitted()
    harness.admin_post(f"{first}/start-review")
    harness.admin_post(f"{first}/reject", {"reason": "The photo on the ID is unreadable."})
    mine = harness.client.get("/api/v1/kyc/submissions/me", headers=bearer(user)).json()
    assert mine["state"] == "REJECTED"
    assert mine["rejection_reason"] == "The photo on the ID is unreadable."
    assert mine["can_resubmit"] is True

    again = harness.submit(user)
    assert again.status_code == 201
    second = again.json()["submission_id"]
    assert second != first
    assert harness.repo.submissions[UUID(first)].state == "REJECTED"  # kept for audit
    latest = harness.client.get("/api/v1/kyc/submissions/me", headers=bearer(user)).json()
    assert latest["submission_id"] == second
    assert harness.repo.transitions[-1].reason == f"resubmission after {first}"
