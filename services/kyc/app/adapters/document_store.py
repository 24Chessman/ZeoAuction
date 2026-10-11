"""KYC document store: object keys in the database, bytes in the encrypted bucket (#39).

The ``kyc-documents`` bucket is private and SSE-S3 encrypted (infra/s3/create-buckets.sh).
Documents are only ever read through a signed GET URL generated per view, valid for
``url_ttl_seconds`` (60 s by default) and never stored or logged (NFR-SEC-2). Nothing in this
module logs bytes, URLs or file names; log lines carry ids only.
"""

import logging

from app.domain.submission import Document, ValidatedUpload
from zeo_common.storage import DEFAULT_SIGNED_URL_TTL, ObjectStore, StorageError, check_ttl

logger = logging.getLogger(__name__)


class DocumentStore:
    def __init__(self, store: ObjectStore, url_ttl_seconds: int = DEFAULT_SIGNED_URL_TTL) -> None:
        self.store = store
        self.url_ttl_seconds = check_ttl(url_ttl_seconds)

    async def save(self, document: Document, upload: ValidatedUpload) -> None:
        if document.sha256 != upload.sha256:
            raise ValueError("document metadata does not match the uploaded bytes")
        await self.store.put(document.object_key, upload.data, upload.mime_type)
        logger.info("Stored KYC document %s (%s, %d bytes)", document.id, document.doc_type,
                    document.size_bytes)

    async def discard(self, documents: list[Document]) -> None:
        """Best-effort removal of objects whose database rows were never committed."""
        for document in documents:
            try:
                await self.store.delete(document.object_key)
            except StorageError:
                logger.warning("Could not remove orphaned KYC document %s", document.id)

    def view_url(self, document: Document) -> str:
        return self.store.signed_url(document.object_key, self.url_ttl_seconds)
