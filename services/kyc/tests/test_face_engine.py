"""The OpenCV adapter. The pure helpers always run; the checks that load YuNet and SFace run
only where the models were fetched (scripts/fetch_face_models.py), so CI without them skips.
No face images are committed: matching quality is measured by hand, see the README."""

import cv2
import numpy as np
import pytest

from app.adapters.face_engine import (
    MAX_SIDE,
    MIN_SIDE,
    FaceModelsMissing,
    OpenCvFaceEngine,
    _decode,
    _fit,
    yaw,
)
from app.settings import SERVICE_ROOT

MODELS = SERVICE_ROOT / "models"
needs_models = pytest.mark.skipif(
    not (MODELS / "face_recognition_sface_2021dec.onnx").is_file(),
    reason="face models not fetched (scripts/fetch_face_models.py)",
)


def encoded(image: np.ndarray, ext: str = ".jpg") -> bytes:
    return cv2.imencode(ext, image)[1].tobytes()


def landmarks(right_eye_x: float, left_eye_x: float, nose_x: float) -> np.ndarray:
    row = np.zeros(15, np.float32)
    row[4], row[6], row[8] = right_eye_x, left_eye_x, nose_x
    return row


def test_yaw_is_the_nose_offset_in_eye_distances():
    assert yaw(landmarks(100, 160, 130)) == pytest.approx(0.0)
    assert yaw(landmarks(100, 160, 145)) == pytest.approx(0.25)
    assert yaw(landmarks(100, 160, 115)) == pytest.approx(-0.25)
    assert yaw(landmarks(100, 100, 100)) == pytest.approx(0.0)  # degenerate: no division by 0


def test_images_are_scaled_into_the_detector_range():
    small = np.zeros((150, 120, 3), np.uint8)
    assert min(_fit(small).shape[:2]) == MIN_SIDE
    large = np.zeros((2000, 3000, 3), np.uint8)
    assert max(_fit(large).shape[:2]) == MAX_SIDE
    ok = np.zeros((480, 640, 3), np.uint8)
    assert _fit(ok) is ok


def test_undecodable_bytes_decode_to_none():
    assert _decode(b"") is None
    assert _decode(b"not an image") is None
    assert _decode(encoded(np.zeros((8, 8, 3), np.uint8))).shape == (8, 8, 3)


def test_missing_models_fail_loudly(tmp_path):
    with pytest.raises(FaceModelsMissing, match="fetch_face_models"):
        OpenCvFaceEngine(tmp_path)


@pytest.fixture(scope="module")
def engine():
    return OpenCvFaceEngine(MODELS)


@needs_models
def test_a_blank_reference_has_no_face_but_is_still_kept_as_jpeg(engine):
    jp2 = encoded(np.full((150, 120, 3), 200, np.uint8), ".jp2")
    reference = engine.reference(jp2)
    assert reference.faces == 0
    assert reference.embedding is None
    assert reference.jpeg.startswith(b"\xff\xd8\xff")


@needs_models
def test_an_undecodable_reference(engine):
    assert engine.reference(b"garbage").jpeg is None


@needs_models
def test_frames_without_faces_read_as_no_face(engine):
    blank = encoded(np.full((480, 640, 3), 90, np.uint8))
    readings = engine.compare(tuple([0.0] * 128), [blank, b"garbage"])
    assert [(r.faces, r.score) for r in readings] == [(0, None), (0, None)]
    assert engine.compare(None, [blank])[0].faces == 0
