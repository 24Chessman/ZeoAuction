"""KYC submissions and their documents (#38; services/kyc/docs/design.md section 4).

Pure logic, no I/O. A document is accepted only if its type is known, its size is within
10 MB and its bytes are really a JPEG, PNG or PDF: the MIME type is sniffed from the content,
never trusted from the upload header. Object keys are built here so they never depend on a
client-supplied file name.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

DOC_TYPES = ("GOVERNMENT_ID", "PROOF_OF_ADDRESS", "SELFIE")
REQUIRED_DOC_TYPES = frozenset({"GOVERNMENT_ID", "PROOF_OF_ADDRESS"})  # SELFIE is optional (SDD)
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # matches the size_bytes CHECK in 20-kyc.sql

# Magic numbers of the accepted formats -> (MIME type, key extension).
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"%PDF-", "application/pdf", "pdf"),
)
ACCEPTED_MIME_TYPES = frozenset(mime for _, mime, _ in _SIGNATURES)
# Header values that say nothing, so they never contradict the sniffed type.
_GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})


class DocumentInvalid(ValueError):
    def __init__(self, doc_type: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.doc_type = doc_type
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
class ValidatedUpload:
    """An upload that passed every check; the bytes travel with it to the store only."""

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


def validate_upload(
    doc_type: str, data: bytes, declared_content_type: str | None,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> ValidatedUpload:
    if doc_type not in DOC_TYPES:
        raise DocumentInvalid(doc_type, "unknown_type", f"Unknown document type {doc_type}")
    if not data:
        raise DocumentInvalid(doc_type, "empty", "The file is empty")
    if len(data) > max_bytes:
        raise DocumentInvalid(
            doc_type, "too_large", f"Each document must be at most {max_bytes // (1024 * 1024)} MB"
        )
    sniffed = sniff(data)
    if sniffed is None:
        raise DocumentInvalid(
            doc_type, "unsupported_format", "Only JPEG, PNG and PDF documents are accepted"
        )
    mime, extension = sniffed
    declared = (declared_content_type or "").split(";")[0].strip().lower()
    if declared not in _GENERIC_CONTENT_TYPES and declared != mime:
        raise DocumentInvalid(
            doc_type, "mime_mismatch", "The file's content does not match its declared type"
        )
    return ValidatedUpload(
        doc_type=doc_type, mime_type=mime, extension=extension, data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def require_documents(uploads: list[ValidatedUpload]) -> None:
    """K1 guard: the required documents are present, each type at most once."""
    types = [upload.doc_type for upload in uploads]
    duplicates = sorted({t for t in types if types.count(t) > 1})
    if duplicates:
        raise DocumentInvalid(duplicates[0], "duplicate_type", "Upload each document type once")
    missing = sorted(REQUIRED_DOC_TYPES - set(types))
    if missing:
        raise DocumentInvalid(missing[0], "missing", f"Required document missing: {missing[0]}")


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
