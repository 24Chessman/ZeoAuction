from datetime import timedelta
from uuid import UUID, uuid4

from app.domain.face import FaceReading
from tests.support import JPEG, PNG, frame, frames, readings


def test_a_clear_match_still_waits_for_an_administrator(harness):
    user, submission_id = harness.submitted()
    response = harness.face(user, submission_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "MATCH"
    assert body["submission"]["state"] == "UNDER_REVIEW"
    assert body["submission"]["face"]["last_outcome"] == "MATCH"
    assert body["submission"]["decided_at"] is None
    assert harness.repo.mirror.users[user] == ("UNDER_REVIEW", 3)
    assert harness.versions.versions[user] == 3
    assert [t.event for t in harness.repo.transitions] == ["submit", "faceMatch"]
    assert harness.repo.audit_log == []  # nobody but the seller acted
    # The engine compared against the template stored with the Aadhaar summary.
    assert harness.engine.compared == [((1.0, 0.0, 0.0), 3)]


def test_the_best_matching_frame_is_kept_as_evidence(harness):
    user, submission_id = harness.submitted()
    harness.engine.next_readings = readings(0.5, 0.7, 0.45)
    harness.face(user, submission_id, frames(3))
    captures = [d for d in harness.repo.docs.values() if d.doc_type == "FACE_CAPTURE"]
    assert len(captures) == 1
    assert harness.store.objects[captures[0].object_key][0] == frame(1)


def test_a_borderline_match_goes_to_an_administrator(harness):
    user, submission_id = harness.in_review()
    assert harness.repo.mirror.users[user][0] == "UNDER_REVIEW"
    assert harness.me(user).json()["state"] == "UNDER_REVIEW"
    assert {d.doc_type for d in harness.repo.docs.values()} == {"AADHAAR_PHOTO", "FACE_CAPTURE"}


def test_failures_count_down_and_the_last_one_rejects(harness):
    user, submission_id = harness.submitted()
    harness.engine.next_readings = readings(0.1, 0.12, 0.09)
    first = harness.face(user, submission_id, frames(3)).json()
    assert (first["outcome"], first["attempts_left"]) == ("NO_MATCH", 2)
    assert first["submission"]["state"] == "SUBMITTED"
    harness.engine.next_readings = readings(0.6, 0.6, 0.6, yaws=(0.0,))
    second = harness.face(user, submission_id, frames(3)).json()
    assert (second["outcome"], second["attempts_left"]) == ("LIVENESS_FAILED", 1)
    harness.engine.next_readings = readings(0.1, 0.12, 0.09)
    third = harness.face(user, submission_id, frames(3)).json()
    assert (third["outcome"], third["attempts_left"]) == ("NO_MATCH", 0)
    assert third["submission"]["state"] == "REJECTED"
    assert third["submission"]["rejection_reason"].startswith("face check NO_MATCH")
    assert harness.repo.mirror.users[user][0] == "REJECTED"
    # Failed frames are never kept.
    assert {d.doc_type for d in harness.repo.docs.values()} == {"AADHAAR_PHOTO"}
    assert [a.attempt_no for a in harness.repo.attempts] == [1, 2, 3]


def test_after_the_last_failure_a_new_upload_waits_for_the_cooldown(harness):
    user, submission_id = harness.submitted()
    harness.engine.next_readings = readings(0.1, 0.1, 0.1)
    for _ in range(3):
        harness.face(user, submission_id, frames(3))
    me = harness.me(user).json()
    assert me["can_resubmit"] is False
    assert me["resubmit_after"] is not None
    refused = harness.upload(user)
    assert refused.status_code == 409
    assert refused.json()["code"] == "KYC_COOLDOWN"
    assert "retry_after" in refused.json()["details"]

    later = harness.repo.submissions[UUID(submission_id)].decided_at + timedelta(hours=25)
    harness.service.clock = lambda: later
    assert harness.me(user).json()["can_resubmit"] is True


def test_no_face_does_not_use_up_an_attempt(harness):
    user, submission_id = harness.submitted()
    harness.engine.next_readings = [FaceReading(faces=0, score=None, yaw=None)] * 3
    body = harness.face(user, submission_id).json()
    assert (body["outcome"], body["attempts_left"]) == ("NO_FACE", 3)
    assert body["submission"]["can_resubmit"] is True


def test_replayed_identical_frames_fail_liveness(harness):
    user, submission_id = harness.submitted()
    body = harness.face(user, submission_id, [frame(1)] * 3).json()
    assert body["outcome"] == "LIVENESS_FAILED"


def test_an_unusable_aadhaar_photo_sends_the_seller_to_review(harness):
    harness.engine.reference_faces = 0
    user, submission_id = harness.submitted()
    assert harness.repo.aadhaar_rows[UUID(submission_id)].reference_embedding is None
    assert harness.face(user, submission_id).json()["outcome"] == "REVIEW"
    assert harness.engine.compared[-1][0] is None


def test_bad_captures_are_refused_without_counting(harness):
    user, submission_id = harness.submitted()
    cases = {
        "frame_count": frames(2),
        "unsupported_format": [b"GIF89a-not-a-frame"] + frames(2),
        "too_large": [JPEG + b"x" * 2048] + frames(2),
    }
    for reason, images in cases.items():
        response = harness.face(user, submission_id, images)
        assert response.status_code == 422, reason
        assert response.json()["code"] == "FACE_CAPTURE_INVALID"
        assert response.json()["details"] == {"reason": reason, "field": "frames"}
    assert harness.repo.attempts == []
    assert harness.face(user, submission_id, frames(9)).json()["details"]["reason"] == (
        "frame_count")


def test_png_frames_are_accepted(harness):
    user, submission_id = harness.submitted()
    pngs = [PNG + f"{n}".encode() for n in range(3)]
    assert harness.face(user, submission_id, pngs).json()["outcome"] == "MATCH"


def test_only_the_owner_can_run_the_check_and_only_while_waiting(harness):
    user, submission_id = harness.submitted()
    assert harness.face(uuid4(), submission_id).status_code == 404
    assert harness.face(user, str(uuid4())).status_code == 404
    harness.face(user, submission_id)
    again = harness.face(user, submission_id)
    assert again.status_code == 409
    assert again.json()["details"] == {"state": "UNDER_REVIEW"}


def test_two_checks_at_once_cannot_both_count(harness):
    from app.adapters.kyc_repo import StaleSubmission

    user, submission_id = harness.submitted()

    async def raced(*args, **kwargs):
        raise StaleSubmission(submission_id)

    harness.repo.record_face_attempt = raced
    response = harness.face(user, submission_id)
    assert response.status_code == 409
    assert {d.doc_type for d in harness.repo.docs.values()} == {"AADHAAR_PHOTO"}
    assert len(harness.store.objects) == 1  # the evidence frame was removed again
