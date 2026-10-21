"""Face detection and recognition with OpenCV: YuNet finds faces and their five landmarks,
SFace turns an aligned face into a 128-number template (both from the OpenCV model zoo,
Apache-2.0, run on the CPU through ``cv2.dnn``).

The models are not in the repository (SFace is 38 MB): ``scripts/fetch_face_models.py``
downloads and checksums them, and the Dockerfile runs it at build time. Calls are blocking
and CPU-bound, so the service runs them with ``asyncio.to_thread``; one lock serialises them
because the networks keep per-call state.

Nothing here logs or keeps images. Templates are L2-normalised, so similarity is a dot product
(the same number as ``FaceRecognizerSF.match`` with ``FR_COSINE``).
"""

import threading
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.domain.face import FaceReading, ReferenceFace

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"
MODEL = "yunet-2023mar+sface-2021dec"

MAX_SIDE = 1280      # larger frames are scaled down before detection
MIN_SIDE = 320       # the Aadhaar photo (often ~160 px wide) is scaled up to this
FRAME_SCORE = 0.8    # YuNet confidence for live frames
REFERENCE_SCORE = 0.6  # the Aadhaar photo is small and compressed, so accept less


class FaceEngine(Protocol):
    model: str

    def reference(self, photo: bytes) -> ReferenceFace: ...

    def compare(self, embedding: tuple[float, ...] | None,
                frames: list[bytes]) -> list[FaceReading]: ...


class FaceModelsMissing(RuntimeError):
    pass


def _decode(data: bytes) -> np.ndarray | None:
    if not data:
        return None
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def _fit(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    longest, shortest = max(height, width), min(height, width)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
    elif shortest < MIN_SIDE:
        scale = MIN_SIDE / shortest
    else:
        return image
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(image, size, interpolation=interpolation)


def yaw(face: np.ndarray) -> float:
    """YuNet row: x, y, w, h, right eye, left eye, nose tip, mouth corners (x, y each), score.
    Facing the camera the nose sits between the eyes (0); turning moves it sideways."""
    right_eye_x, left_eye_x, nose_x = face[4], face[6], face[8]
    eye_distance = max(abs(left_eye_x - right_eye_x), 1.0)
    return float((nose_x - (right_eye_x + left_eye_x) / 2) / eye_distance)


class OpenCvFaceEngine:
    model = MODEL

    def __init__(self, models_dir: Path) -> None:
        detector, recognizer = models_dir / DETECTOR_FILE, models_dir / RECOGNIZER_FILE
        missing = [p.name for p in (detector, recognizer) if not p.is_file()]
        if missing:
            raise FaceModelsMissing(
                f"Face models missing in {models_dir}: {', '.join(missing)}. "
                "Run services/kyc/scripts/fetch_face_models.py"
            )
        self._detector = cv2.FaceDetectorYN.create(
            str(detector), "", (MIN_SIDE, MIN_SIDE), FRAME_SCORE, 0.3, 5000
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer), "")
        self._lock = threading.Lock()

    def _detect(self, image: np.ndarray, threshold: float) -> tuple[np.ndarray, np.ndarray]:
        image = _fit(image)
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        self._detector.setScoreThreshold(threshold)
        _, faces = self._detector.detect(image)
        return image, (faces if faces is not None else np.empty((0, 15), np.float32))

    def _embed(self, image: np.ndarray, face: np.ndarray) -> np.ndarray:
        aligned = self._recognizer.alignCrop(image, face)
        feature = self._recognizer.feature(aligned).flatten().astype(np.float64)
        return feature / max(np.linalg.norm(feature), 1e-12)

    def reference(self, photo: bytes) -> ReferenceFace:
        image = _decode(photo)
        if image is None:
            return ReferenceFace(jpeg=None, faces=0, embedding=None)
        encoded, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        jpeg = buffer.tobytes() if encoded else None
        with self._lock:
            scaled, faces = self._detect(image, REFERENCE_SCORE)
            if len(faces) != 1:
                return ReferenceFace(jpeg=jpeg, faces=len(faces), embedding=None)
            embedding = self._embed(scaled, faces[0])
        return ReferenceFace(jpeg=jpeg, faces=1, embedding=tuple(float(v) for v in embedding))

    def compare(self, embedding: tuple[float, ...] | None,
                frames: list[bytes]) -> list[FaceReading]:
        """Without a reference template (no usable face in the Aadhaar photo) faces and yaw
        are still measured, for liveness, and every score is 0."""
        reference = None if embedding is None else np.asarray(embedding, dtype=np.float64)
        readings = []
        for frame in frames:
            image = _decode(frame)
            if image is None:
                readings.append(FaceReading(faces=0, score=None, yaw=None))
                continue
            with self._lock:
                scaled, faces = self._detect(image, FRAME_SCORE)
                if len(faces) != 1:
                    readings.append(FaceReading(faces=len(faces), score=None, yaw=None))
                    continue
                template = self._embed(scaled, faces[0])
                score = 0.0 if reference is None else float(np.dot(template, reference))
            readings.append(FaceReading(faces=1, score=score, yaw=yaw(faces[0])))
        return readings
