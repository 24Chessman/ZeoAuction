"""KYC submissions and the images they keep (services/kyc/README.md).

Pure logic, no I/O. A submission keeps at most two images, both JPEG or PNG:

- ``AADHAAR_PHOTO``: the photo from the seller's signed Aadhaar Secure QR, re-encoded as JPEG
  (UIDAI issues JPEG 2000, which browsers do not render);
- ``FACE_CAPTURE``: the best live frame of a face check that matched or went to review.

A frame's MIME type is sniffed from its bytes, never trusted from the upload header. Object
keys are built here so they never depend on a client-supplied file name.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

DOC_TYPES = ("AADHAAR_PHOTO", "FACE_CAPTURE")
MAX_FRAME_BYTES = 2 * 1024 * 1024  # one webcam frame; well under the 10 MB CHECK in 20-kyc.sql

# Magic numbers of the accepted formats -> (MIME type, key extension).
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)
ACCEPTED_MIME_TYPES = frozenset(mime for _, mime, _ in _SIGNATURES)


class ImageInvalid(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Submission:
    id: UUID
    user_id: UUID
    state: str
    rejection_reason: str | None
    submitted_at: datetime
    decided_at: datetime | None
    decided_by: UUID | None
    updated_at: datetime


@dataclass(frozen=True)
class Document:
    id: UUID
    submission_id: UUID
    doc_type: str
    object_key: str
    mime_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    purge_after: datetime


@dataclass(frozen=True)
class FaceAttempt:
    """Legacy persistence shape retained for existing database compatibility."""

    submission_id: UUID
    attempt_no: int
    frames: int
    good_frames: int
    median_score: float | None
    min_score: float | None
    yaw_span: float | None
    outcome: str
    at: datetime


@dataclass(frozen=True)
class ValidatedUpload:
    """An image that passed every check; the bytes travel with it to the store only."""

    doc_type: str
    mime_type: str
    extension: str
    data: bytes
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def sniff(data: bytes) -> tuple[str, str] | None:
    for magic, mime, extension in _SIGNATURES:
        if data.startswith(magic):
            return mime, extension
    return None


def validate_image(doc_type: str, data: bytes, max_bytes: int = MAX_FRAME_BYTES) -> ValidatedUpload:
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown document type {doc_type}")
    if not data:
        raise ImageInvalid("empty", "An image is empty")
    if len(data) > max_bytes:
        raise ImageInvalid(
            "too_large", f"Each image must be at most {max_bytes // 1024} KB"
        )
    sniffed = sniff(data)
    if sniffed is None:
        raise ImageInvalid("unsupported_format", "Only JPEG and PNG images are accepted")
    mime, extension = sniffed
    return ValidatedUpload(
        doc_type=doc_type, mime_type=mime, extension=extension, data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def object_key(user_id: UUID, submission_id: UUID, doc_type: str, doc_id: UUID,
               extension: str) -> str:
    """``kyc/{user_id}/{submission_id}/{doc_type}-{doc_id}.{ext}``: ids only, no file names."""
    return f"kyc/{user_id}/{submission_id}/{doc_type}-{doc_id}.{extension}"


def new_document(
    upload: ValidatedUpload, *, doc_id: UUID, submission: Submission, now: datetime,
    retention_days: int,
) -> Document:
    return Document(
        id=doc_id,
        submission_id=submission.id,
        doc_type=upload.doc_type,
        object_key=object_key(submission.user_id, submission.id, upload.doc_type, doc_id,
                              upload.extension),
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256,
        uploaded_at=now,
        # Retention ADR pending (FR-DOC-4): the purge job (Plan 6) deletes after this.
        purge_after=now + timedelta(days=retention_days),
    )
