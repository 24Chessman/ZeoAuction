import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.adapters.document_store import DocumentStore
from app.domain.submission import (
    Submission,
    new_document,
    object_key,
    require_documents,
    validate_upload,
)
from tests.support import PDF, PNG
from zeo_common.storage import InMemoryObjectStore, StorageError

NOW = datetime(2026, 9, 10, tzinfo=UTC)
SUBMISSION = Submission(id=uuid4(), user_id=uuid4(), state="SUBMITTED", rejection_reason=None,
                        submitted_at=NOW, decided_at=None, decided_by=None, updated_at=NOW)


def document(data=PDF, doc_type="GOVERNMENT_ID"):
    upload = validate_upload(doc_type, data, "application/pdf" if data == PDF else None)
    return new_document(upload, doc_id=uuid4(), submission=SUBMISSION, now=NOW,
                        retention_days=90), upload


async def test_save_stores_bytes_under_the_object_key_and_never_logs_them(caplog):
    store = InMemoryObjectStore("kyc-documents")
    documents = DocumentStore(store)
    doc, upload = document()
    with caplog.at_level(logging.DEBUG):
        await documents.save(doc, upload)
    assert store.objects[doc.object_key] == (PDF, "application/pdf")
    assert "%PDF" not in caplog.text
    assert doc.object_key not in caplog.text


async def test_metadata_must_match_the_bytes():
    doc, upload = document()
    with pytest.raises(ValueError):
        await DocumentStore(InMemoryObjectStore()).save(replace(doc, sha256="0" * 64), upload)


def test_view_url_is_signed_with_the_configured_ttl():
    doc, _ = document()
    url = DocumentStore(InMemoryObjectStore(), url_ttl_seconds=30).view_url(doc)
    assert "X-Amz-Expires=30" in url
    assert doc.object_key in url


def test_ttl_is_bounded():
    with pytest.raises(ValueError):
        DocumentStore(InMemoryObjectStore(), url_ttl_seconds=3600)


async def test_discard_is_best_effort():
    class FailingDelete(InMemoryObjectStore):
        async def delete(self, key):
            raise StorageError("DELETE returned 500")

    doc, _ = document()
    await DocumentStore(FailingDelete()).discard([doc])  # logged, not raised


def test_retention_and_keys():
    doc, _ = document()
    assert doc.purge_after == NOW + timedelta(days=90)
    assert doc.object_key == object_key(SUBMISSION.user_id, SUBMISSION.id, "GOVERNMENT_ID",
                                        doc.id, "pdf")


def test_duplicate_types_are_refused():
    upload = validate_upload("GOVERNMENT_ID", PDF, None)
    proof = validate_upload("PROOF_OF_ADDRESS", PNG, "image/png; charset=binary")
    require_documents([upload, proof])
    with pytest.raises(ValueError):
        require_documents([upload, upload, proof])
