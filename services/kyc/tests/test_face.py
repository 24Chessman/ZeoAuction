from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.face import (
    FaceAttempt,
    FaceCaptureInvalid,
    FacePolicy,
    FaceReading,
    assess,
    attempts_left,
    check_frame_count,
    counted,
    event_for,
)
from tests.support import readings

POLICY = FacePolicy()
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def decide(values, *, reference_usable=True, duplicate_frames=False):
    return assess(values, reference_usable=reference_usable,
                  duplicate_frames=duplicate_frames, policy=POLICY)


def attempt(outcome: str, n: int = 1) -> FaceAttempt:
    return FaceAttempt(submission_id=uuid4(), attempt_no=n, frames=3, good_frames=3,
                       median_score=0.1, min_score=0.1, yaw_span=0.3, outcome=outcome, at=NOW)


def test_a_clear_match_with_a_turning_head_matches():
    result = decide(readings(0.55, 0.61, 0.48))
    assert result.outcome == "MATCH"
    assert result.median_score == pytest.approx(0.55)
    assert result.min_score == pytest.approx(0.48)
    assert result.yaw_span == pytest.approx(0.4)
    assert result.best_frame == 1
    assert (result.frames, result.good_frames) == (3, 3)


def test_a_match_needs_every_frame_to_be_plausibly_the_same_person():
    # Median clears the bar but one frame looks like someone else: a person swap mid-capture.
    assert decide(readings(0.6, 0.62, 0.1)).outcome == "REVIEW"


def test_the_borderline_band_goes_to_review():
    assert decide(readings(0.35, 0.33, 0.38)).outcome == "REVIEW"


def test_a_low_similarity_is_no_match():
    assert decide(readings(0.12, 0.08, 0.15)).outcome == "NO_MATCH"


def test_a_head_that_never_turns_fails_liveness():
    assert decide(readings(0.6, 0.6, 0.6, yaws=(0.01, 0.02, 0.03))).outcome == (
        "LIVENESS_FAILED")


def test_duplicate_frames_fail_liveness_before_anything_else():
    assert decide(readings(0.6, 0.6, 0.6), duplicate_frames=True).outcome == "LIVENESS_FAILED"


def test_too_few_single_face_frames_is_no_face():
    values = readings(0.6, 0.6) + [FaceReading(faces=0, score=None, yaw=None)]
    assert decide(values).outcome == "NO_FACE"
    crowd = [FaceReading(faces=2, score=None, yaw=None)] * 3
    assert decide(crowd).outcome == "NO_FACE"
    assert decide(crowd).best_frame is None


def test_an_unusable_aadhaar_photo_sends_a_live_person_to_review():
    assert decide(readings(0.0, 0.0, 0.0), reference_usable=False).outcome == "REVIEW"
    # Liveness is still enforced first.
    still = readings(0.0, 0.0, 0.0, yaws=(0.0,))
    assert decide(still, reference_usable=False).outcome == "LIVENESS_FAILED"


def test_frames_without_yaw_cannot_prove_liveness():
    values = [FaceReading(faces=1, score=0.6, yaw=None)] * 3
    assert decide(values).outcome == "LIVENESS_FAILED"


def test_frame_count_limits():
    check_frame_count(3, POLICY)
    check_frame_count(8, POLICY)
    for bad in (0, 2, 9):
        with pytest.raises(FaceCaptureInvalid):
            check_frame_count(bad, POLICY)


def test_only_failures_count_as_attempts():
    history = [attempt("NO_FACE"), attempt("NO_MATCH", 2), attempt("LIVENESS_FAILED", 3)]
    assert counted(history) == 2
    assert attempts_left(history, POLICY) == 1
    assert attempts_left(history * 3, POLICY) == 0


@pytest.mark.parametrize(
    ("outcome", "counted_after", "event"),
    [("MATCH", 0, "faceMatch"), ("REVIEW", 2, "faceReview"), ("NO_MATCH", 1, None),
     ("NO_MATCH", 3, "faceFail"), ("LIVENESS_FAILED", 3, "faceFail"), ("NO_FACE", 3, None)],
)
def test_events(outcome, counted_after, event):
    assert event_for(outcome, counted_after, POLICY) == event
