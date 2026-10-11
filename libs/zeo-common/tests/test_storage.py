from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from zeo_common.storage import (
    EMPTY_SHA256,
    MAX_SIGNED_URL_TTL,
    InMemoryObjectStore,
    InvalidObjectKey,
    S3ObjectStore,
    SigV4Signer,
    StorageError,
    StorageSettings,
    validate_object_key,
)

# The worked examples from the AWS Signature Version 4 documentation for S3.
AWS_EXAMPLE = SigV4Signer("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
AWS_DATE = datetime(2013, 5, 24, tzinfo=UTC)
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def test_presigned_url_matches_the_aws_documentation_example():
    url = AWS_EXAMPLE.presign(
        "GET", "https://examplebucket.s3.amazonaws.com/test.txt", 86400, AWS_DATE
    )
    signature = parse_qs(urlsplit(url).query)["X-Amz-Signature"][0]
    assert signature == "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"


def test_header_signature_matches_the_aws_documentation_example():
    headers = AWS_EXAMPLE.sign_headers(
        "GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"},
        EMPTY_SHA256, AWS_DATE,
    )
    assert headers["authorization"].endswith(
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in headers["authorization"]


@pytest.mark.parametrize(
    "key",
    ["", "/abs/key", "https://evil.example/x", "a//b", "a/../b", "a/./b", "a\\b", "x" * 1025],
)
def test_keys_that_are_not_relative_paths_are_refused(key):
    with pytest.raises(InvalidObjectKey):
        validate_object_key(key)


def test_a_normal_key_is_accepted():
    assert validate_object_key("kyc/u1/s1/GOVERNMENT_ID-1.pdf") == "kyc/u1/s1/GOVERNMENT_ID-1.pdf"


def settings(**overrides):
    values = {
        "endpoint_url": "http://s3:8333", "access_key": "ak", "secret_key": "sk",
        "bucket": "kyc-documents", "public_endpoint_url": "http://localhost:8333",
    }
    return StorageSettings(**(values | overrides))


def recording_store(status: int = 200, **overrides):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return S3ObjectStore(settings(**overrides), http, clock=lambda: NOW), seen


async def test_put_is_signed_and_asks_for_encryption_at_rest():
    store, seen = recording_store()
    await store.put("kyc/u/s/doc.pdf", b"%PDF-1.7", "application/pdf")
    (request,) = seen
    assert request.method == "PUT"
    assert str(request.url) == "http://s3:8333/kyc-documents/kyc/u/s/doc.pdf"
    assert request.headers["x-amz-server-side-encryption"] == "AES256"
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=ak/20260910/")
    assert request.content == b"%PDF-1.7"
    await store.aclose()


async def test_unencrypted_buckets_do_not_send_the_sse_header():
    store, seen = recording_store(encrypted=False)
    await store.put("listing/1.png", b"x", "image/png")
    assert "x-amz-server-side-encryption" not in seen[0].headers


async def test_a_refused_put_raises_without_leaking_the_url():
    store, _ = recording_store(status=403)
    with pytest.raises(StorageError) as error:
        await store.put("kyc/u/s/doc.pdf", b"x", "application/pdf")
    assert "http" not in str(error.value)
    assert "403" in str(error.value)


async def test_transport_failure_is_a_storage_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    store = S3ObjectStore(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(StorageError):
        await store.delete("kyc/u/s/doc.pdf")


async def test_delete_tolerates_a_missing_object_but_not_other_errors():
    store, seen = recording_store(status=404)
    await store.delete("kyc/u/s/doc.pdf")
    assert seen[0].method == "DELETE"
    failing, _ = recording_store(status=500)
    with pytest.raises(StorageError):
        await failing.delete("kyc/u/s/doc.pdf")


def test_signed_url_points_at_the_public_host_and_expires():
    store, _ = recording_store()
    url = store.signed_url("kyc/u/s/doc.pdf", ttl_seconds=60)
    parts = urlsplit(url)
    assert parts.netloc == "localhost:8333"
    assert parts.path == "/kyc-documents/kyc/u/s/doc.pdf"
    query = parse_qs(parts.query)
    assert query["X-Amz-Expires"] == ["60"]
    assert query["X-Amz-Date"] == ["20260910T120000Z"]


@pytest.mark.parametrize("ttl", [0, MAX_SIGNED_URL_TTL + 1])
def test_signed_url_ttl_is_bounded(ttl):
    store, _ = recording_store()
    with pytest.raises(ValueError):
        store.signed_url("kyc/u/s/doc.pdf", ttl_seconds=ttl)


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "dispute-evidence")
    monkeypatch.setenv("S3_ENCRYPTED", "false")
    loaded = StorageSettings.from_env("kyc-documents")
    assert loaded.bucket == "dispute-evidence"
    assert loaded.encrypted is False
    assert loaded.public_endpoint_url == "http://localhost:8333"


async def test_in_memory_store_round_trip():
    store = InMemoryObjectStore("kyc-documents", clock=lambda: NOW)
    await store.put("a/b.pdf", b"data", "application/pdf")
    assert store.objects["a/b.pdf"] == (b"data", "application/pdf")
    assert "X-Amz-Expires=60" in store.signed_url("a/b.pdf")
    await store.delete("a/b.pdf")
    assert store.objects == {}
    store.fail_next_put = True
    with pytest.raises(StorageError):
        await store.put("a/c.pdf", b"x", "application/pdf")
    with pytest.raises(InvalidObjectKey):
        await store.put("s3://bucket/key", b"x", "application/pdf")
