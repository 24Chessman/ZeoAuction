from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from scripts.synthetic_qr import Holder
from tests.support import JPEG, bearer, qr_image, readings
from zeo_common.contract_testing import assert_matches_contract


def test_a_verified_aadhaar_creates_a_submission_waiting_for_the_face(harness):
    user = uuid4()
    response = harness.upload(user, mobile="9876543210")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "SUBMITTED"
    assert body["aadhaar"]["holder_name"] == "Asha Verma"
    assert body["aadhaar"]["reference_last4"] == "3632"
    assert body["aadhaar"]["mobile_verified"] is True
    assert body["face"] == {"attempts_used": 0, "attempts_left": 3, "last_outcome": None}
    assert body["can_resubmit"] is True  # no counted face attempt yet: may replace the QR
    assert [d["doc_type"] for d in body["documents"]] == ["AADHAAR_PHOTO"]
    assert "url" not in str(body).lower()


def test_nothing_identifying_beyond_the_summary_is_kept_or_returned(harness):
    user = uuid4()
    body = harness.upload(user, mobile="9876543210").json()
    assert "pincode" not in body["aadhaar"]  # sellers see less than reviewers
    (summary,) = harness.repo.aadhaar_rows.values()
    assert summary.reference_embedding == (1.0, 0.0, 0.0)
    kept = repr(summary) + repr(list(harness.store.objects))
    for secret in ("9876543210", "Maharashtra Pune", "FC Road"):
        assert secret not in kept
    (key,) = harness.store.objects
    assert key.startswith(f"kyc/{user}/{body['submission_id']}/AADHAAR_PHOTO-")
    assert harness.store.objects[key][1] == "image/jpeg"


def test_upload_mirrors_the_status_and_forces_a_token_refresh(harness):
    user = uuid4()
    harness.upload(user)
    assert harness.repo.mirror.users[user] == ("SUBMITTED", 2)
    assert harness.versions.versions[user] == 2
    (transition,) = harness.repo.transitions
    assert (transition.event, transition.to_state, transition.actor_id) == (
        "submit", "SUBMITTED", user)


def test_an_invalid_qr_names_the_reason_and_the_field(harness):
    response = harness.upload(uuid4(), mobile="9999999999")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "AADHAAR_INVALID"
    assert body["details"] == {"reason": "mobile_mismatch", "field": "mobile"}
    assert_matches_contract(body, "openapi/common.v1.yaml", "/components/schemas/Error")
    assert harness.store.objects == {}
    assert harness.repo.submissions == {}


def test_an_old_card_is_accepted_but_an_underage_holder_is_not(harness):
    old = qr_image(generated_at=datetime.now(UTC) - timedelta(days=4 * 365))
    assert harness.upload(uuid4(), old).status_code == 201
    young = qr_image(Holder(dob="01-01-2015"))
    assert harness.upload(uuid4(), young).json()["details"]["reason"] == "underage"


def test_photos_without_a_qr_or_that_are_not_images_are_refused(harness):
    import cv2
    import numpy as np

    ok, blank = cv2.imencode(".png", np.full((200, 200), 255, np.uint8))
    response = harness.upload(uuid4(), blank.tobytes())
    assert response.json()["details"] == {"reason": "no_qr", "field": "qr_image"}
    assert harness.upload(uuid4(), b"%PDF-1.7").json()["details"]["reason"] == "not_image"
    assert harness.upload(uuid4(), JPEG).json()["details"]["reason"] == "not_image"


def test_an_undecodable_photo_is_refused(harness):
    harness.engine.decodable = False
    response = harness.upload(uuid4())
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "no_photo"


def test_uploads_require_a_token_and_an_image(harness):
    files = {"qr_image": ("qr.png", qr_image(), "image/png")}
    assert harness.client.post("/api/v1/kyc/aadhaar", files=files).status_code == 401
    response = harness.client.post("/api/v1/kyc/aadhaar", data={"mobile": "9876543210"},
                                   headers=bearer(uuid4()))
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_re_uploading_before_any_face_attempt_withdraws_the_waiting_row(harness):
    user, first = harness.submitted()
    second = harness.upload(user)
    assert second.status_code == 201
    assert second.json()["submission_id"] != first
    old = harness.repo.submissions[UUID(first)]
    assert (old.state, old.rejection_reason) == (
        "REJECTED", "Replaced by a new Aadhaar QR upload")
    assert [t.event for t in harness.repo.transitions] == ["submit", "withdraw", "submit"]


def test_a_counted_face_attempt_locks_the_qr(harness):
    user, submission_id = harness.submitted()
    harness.engine.next_readings = readings(0.1, 0.1, 0.1)
    assert harness.face(user, submission_id).json()["outcome"] == "NO_MATCH"
    response = harness.upload(user)
    assert response.status_code == 409
    assert response.json()["code"] == "KYC_ALREADY_ACTIVE"
    assert response.json()["details"] == {"state": "SUBMITTED"}
    assert harness.me(user).json()["can_resubmit"] is False


def test_a_verified_seller_cannot_upload_again(harness):
    user, submission_id = harness.submitted()
    assert harness.face(user, submission_id).json()["outcome"] == "MATCH"
    harness.admin_post(f"{submission_id}/approve")
    response = harness.upload(user)
    assert response.status_code == 409
    assert response.json()["details"] == {"state": "VERIFIED"}


def test_my_submission(harness):
    user, submission_id = harness.submitted()
    response = harness.me(user)
    assert response.status_code == 200
    assert response.json()["submission_id"] == submission_id


def test_my_submission_before_submitting_is_not_found(harness):
    response = harness.me(uuid4())
    assert response.status_code == 404
    assert response.json()["details"] == {"kyc_status": "NOT_SUBMITTED"}


def test_a_lost_race_on_create_removes_the_stored_photo(harness):
    from app.adapters.kyc_repo import ActiveSubmissionExists

    async def lose(*args, **kwargs):
        raise ActiveSubmissionExists("someone else")

    harness.repo.create = lose
    response = harness.upload(uuid4())
    assert response.status_code == 409
    assert harness.store.objects == {}


def test_storage_outage_saves_nothing(harness):
    from zeo_common.storage import StorageError

    async def down(*args, **kwargs):
        raise StorageError("PUT returned 503")

    harness.store.put = down
    response = harness.upload(uuid4())
    assert response.status_code == 503
    assert harness.repo.submissions == {}
