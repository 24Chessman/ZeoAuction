"""The live face check: does the person at the camera match the Aadhaar photo?

Pure logic, no I/O. The face engine (``app/adapters/face_engine.py``) turns each frame into a
:class:`FaceReading`: how many faces it found, the cosine similarity of the face to the Aadhaar
photo's template, and a yaw estimate from the landmarks. :func:`assess` decides:

1. Duplicate frames, or a head that never turned, fail liveness (``LIVENESS_FAILED``). This is a
   basic check against a held-up photo, not a certified presentation-attack detector.
2. Too few frames with exactly one face is ``NO_FACE`` (lighting, framing). It does not count
   as an attempt.
3. No usable face in the Aadhaar photo sends the submission to an administrator (``REVIEW``).
4. Otherwise the median similarity decides: ``MATCH`` at or above ``match_threshold`` (every
   frame at least ``review_threshold``), ``REVIEW`` at or above ``review_threshold``,
   ``NO_MATCH`` below.

``NO_MATCH`` and ``LIVENESS_FAILED`` count as attempts; the last allowed one rejects the
submission (K4a), and a new upload must wait for the cooldown.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

OUTCOMES = ("MATCH", "REVIEW", "NO_MATCH", "LIVENESS_FAILED", "NO_FACE")
COUNTED_OUTCOMES = frozenset({"NO_MATCH", "LIVENESS_FAILED"})
# Outcome -> the transition it makes from SUBMITTED (docs/state-machines.md section 3).
_EVENTS = {"MATCH": "faceMatch", "REVIEW": "faceReview"}


class FaceCaptureInvalid(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class FacePolicy:
    """Thresholds are for OpenCV SFace cosine similarity. OpenCV's own same-person threshold
    is 0.363 on good photos; Aadhaar photos are small and often years old, hence the review
    band below an automatic match. Tune with KYC_FACE_* settings."""

    match_threshold: float = 0.42
    review_threshold: float = 0.30
    min_frames: int = 3
    max_frames: int = 8
    min_yaw_span: float = 0.12
    max_attempts: int = 3
    cooldown: timedelta = timedelta(hours=24)


@dataclass(frozen=True)
class ReferenceFace:
    """The Aadhaar photo as the engine saw it: re-encoded JPEG (None if undecodable), the
    number of faces found, and the template when exactly one was found."""

    jpeg: bytes | None
    faces: int
    embedding: tuple[float, ...] | None


@dataclass(frozen=True)
class FaceReading:
    faces: int
    score: float | None  # cosine similarity to the reference; None unless exactly one face
    yaw: float | None    # nose offset from the eye midpoint, in eye distances


@dataclass(frozen=True)
class FaceAssessment:
    outcome: str
    frames: int
    good_frames: int
    median_score: float | None
    min_score: float | None
    yaw_span: float | None
    best_frame: int | None  # index of the most similar frame, kept as evidence


@dataclass(frozen=True)
class FaceAttempt:
    """One row of the append-only ``kyc.face_match_attempts``."""

    submission_id: UUID
    attempt_no: int
    frames: int
    good_frames: int
    median_score: float | None
    min_score: float | None
    yaw_span: float | None
    outcome: str
    at: datetime


def check_frame_count(count: int, policy: FacePolicy) -> None:
    if not policy.min_frames <= count <= policy.max_frames:
        raise FaceCaptureInvalid(
            "frame_count",
            f"Send between {policy.min_frames} and {policy.max_frames} camera frames",
        )


def assess(
    readings: list[FaceReading], *, reference_usable: bool, duplicate_frames: bool,
    policy: FacePolicy,
) -> FaceAssessment:
    good = [(i, r) for i, r in enumerate(readings) if r.faces == 1 and r.score is not None]
    scores = [r.score for _, r in good]
    yaws = [r.yaw for _, r in good if r.yaw is not None]
    median = statistics.median(scores) if scores else None
    lowest = min(scores) if scores else None
    yaw_span = (max(yaws) - min(yaws)) if len(yaws) >= 2 else None
    best = max(good, key=lambda pair: pair[1].score)[0] if good else None

    def result(outcome: str) -> FaceAssessment:
        return FaceAssessment(
            outcome=outcome, frames=len(readings), good_frames=len(good), median_score=median,
            min_score=lowest, yaw_span=yaw_span, best_frame=best,
        )

    if duplicate_frames:
        return result("LIVENESS_FAILED")
    if len(good) < policy.min_frames:
        return result("NO_FACE")
    if yaw_span is None or yaw_span < policy.min_yaw_span:
        return result("LIVENESS_FAILED")
    if not reference_usable:
        return result("REVIEW")
    if median >= policy.match_threshold and lowest >= policy.review_threshold:
        return result("MATCH")
    if median >= policy.review_threshold:
        return result("REVIEW")
    return result("NO_MATCH")


def counted(attempts: list[FaceAttempt]) -> int:
    return sum(1 for attempt in attempts if attempt.outcome in COUNTED_OUTCOMES)


def attempts_left(attempts: list[FaceAttempt], policy: FacePolicy) -> int:
    return max(0, policy.max_attempts - counted(attempts))


def event_for(outcome: str, counted_after: int, policy: FacePolicy) -> str | None:
    """The transition an attempt makes, given the counted attempts including this one."""
    if outcome in _EVENTS:
        return _EVENTS[outcome]
    if outcome in COUNTED_OUTCOMES and counted_after >= policy.max_attempts:
        return "faceFail"
    return None
