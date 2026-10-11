"""S3-compatible object storage with short-TTL signed URLs (#96, NFR-SEC-2, SDD 4.5).

Private buckets (``kyc-documents``, ``dispute-evidence``) are read **only** through signed GET
URLs that expire in seconds, generated per view and never stored or logged. Tables store the
object key, never a URL. Uploads to an encrypted bucket ask for SSE-S3 explicitly, on top of
the bucket default set by ``infra/s3/create-buckets.sh``.

Requests are signed with AWS Signature Version 4 directly (path-style addressing, which
SeaweedFS locally and every S3-compatible host accept), so services need no AWS SDK.

    store = S3ObjectStore(StorageSettings.from_env())
    await store.put("kyc/u/s/GOVERNMENT_ID-x.pdf", data, "application/pdf")
    url = store.signed_url("kyc/u/s/GOVERNMENT_ID-x.pdf", ttl_seconds=60)
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx

from zeo_common.settings import env_bool, env_str

DEFAULT_SIGNED_URL_TTL = 60
MAX_SIGNED_URL_TTL = 300  # anything longer is a stored link in disguise
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ALGORITHM = "AWS4-HMAC-SHA256"


class StorageError(Exception):
    """The object store refused or failed a request. The message never contains a URL."""


class InvalidObjectKey(ValueError):
    pass


def validate_object_key(key: str) -> str:
    """Object keys are relative paths. Anything that looks like a URL is refused, which is
    the same rule as the ``object_key`` CHECK constraints in the schema."""
    if not key or len(key) > 1024:
        raise InvalidObjectKey("object key must be 1 to 1024 characters")
    if "://" in key or key.startswith("/") or "\\" in key:
        raise InvalidObjectKey("object key must be a relative path, never a URL")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise InvalidObjectKey("object key must not contain empty, '.' or '..' segments")
    return key


def check_ttl(ttl_seconds: int) -> int:
    if not 1 <= ttl_seconds <= MAX_SIGNED_URL_TTL:
        raise ValueError(f"signed URL TTL must be 1 to {MAX_SIGNED_URL_TTL} seconds")
    return ttl_seconds


@dataclass(frozen=True)
class StorageSettings:
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"
    # Host the browser can reach. In Compose the services reach "http://s3:8333", but a
    # signed URL handed to the SPA must point at "http://localhost:8333".
    public_endpoint_url: str | None = None
    encrypted: bool = True

    @classmethod
    def from_env(cls, default_bucket: str, *, encrypted: bool = True) -> "StorageSettings":
        return cls(
            endpoint_url=env_str("S3_ENDPOINT_URL", "http://localhost:8333"),
            # LOCAL DEVELOPMENT ONLY defaults (infra/s3/s3-identities.json).
            access_key=env_str("S3_ACCESS_KEY", "zeo-dev-access"),
            secret_key=env_str("S3_SECRET_KEY", "zeo-dev-secret"),
            bucket=env_str("S3_BUCKET", default_bucket),
            region=env_str("S3_REGION", "us-east-1"),
            public_endpoint_url=env_str("S3_PUBLIC_ENDPOINT_URL", "http://localhost:8333"),
            encrypted=env_bool("S3_ENCRYPTED", encrypted),
        )


# ---------------------------------------------------------------------- Signature V4


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, day: str, region: str, service: str) -> bytes:
    key = _hmac(("AWS4" + secret_key).encode("utf-8"), day)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


def _encode_path(path: str) -> str:
    return quote(path, safe="/-_.~")


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items())
    )


@dataclass(frozen=True)
class SigV4Signer:
    access_key: str
    secret_key: str
    region: str = "us-east-1"
    service: str = "s3"

    def _scope(self, day: str) -> str:
        return f"{day}/{self.region}/{self.service}/aws4_request"

    def _signature(self, canonical_request: str, amz_date: str) -> str:
        day = amz_date[:8]
        string_to_sign = "\n".join(
            (ALGORITHM, amz_date, self._scope(day),
             hashlib.sha256(canonical_request.encode("utf-8")).hexdigest())
        )
        key = _signing_key(self.secret_key, day, self.region, self.service)
        return hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    def presign(self, method: str, url: str, expires: int, now: datetime) -> str:
        """Query-string authentication: a URL usable without credentials until it expires."""
        parts = urlsplit(url)
        amz_date = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        params = {
            "X-Amz-Algorithm": ALGORITHM,
            "X-Amz-Credential": f"{self.access_key}/{self._scope(amz_date[:8])}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires),
            "X-Amz-SignedHeaders": "host",
        }
        query = _canonical_query(params)
        path = _encode_path(parts.path or "/")
        canonical = "\n".join(
            (method, path, query, f"host:{parts.netloc}\n", "host", "UNSIGNED-PAYLOAD")
        )
        signature = self._signature(canonical, amz_date)
        return f"{parts.scheme}://{parts.netloc}{path}?{query}&X-Amz-Signature={signature}"

    def sign_headers(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload_sha256: str,
        now: datetime,
    ) -> dict[str, str]:
        """Header authentication. Returns ``headers`` plus ``x-amz-*`` and ``Authorization``."""
        parts = urlsplit(url)
        amz_date = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        signed = {k.lower(): v.strip() for k, v in headers.items()}
        signed |= {
            "host": parts.netloc,
            "x-amz-content-sha256": payload_sha256,
            "x-amz-date": amz_date,
        }
        names = sorted(signed)
        canonical_headers = "".join(f"{name}:{signed[name]}\n" for name in names)
        signed_headers = ";".join(names)
        query = "&".join(sorted(parts.query.split("&"))) if parts.query else ""
        canonical = "\n".join(
            (method, _encode_path(parts.path or "/"), query, canonical_headers,
             signed_headers, payload_sha256)
        )
        signature = self._signature(canonical, amz_date)
        authorization = (
            f"{ALGORITHM} Credential={self.access_key}/{self._scope(amz_date[:8])}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        result = {k: v for k, v in signed.items() if k != "host"}
        result["authorization"] = authorization
        return result


# ---------------------------------------------------------------------- stores


class ObjectStore(Protocol):
    bucket: str

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    def signed_url(self, key: str, ttl_seconds: int = DEFAULT_SIGNED_URL_TTL) -> str: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class S3ObjectStore:
    """Path-style S3 client over ``httpx``. Errors carry the status, never the URL."""

    def __init__(
        self,
        settings: StorageSettings,
        http: httpx.AsyncClient | None = None,
        clock: Any = _utc_now,
    ) -> None:
        self.settings = settings
        self.bucket = settings.bucket
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self.signer = SigV4Signer(settings.access_key, settings.secret_key, settings.region)
        self._clock = clock

    def _url(self, key: str, *, public: bool = False) -> str:
        base = (self.settings.public_endpoint_url if public else None) or self.settings.endpoint_url
        return f"{base.rstrip('/')}/{self.bucket}/{validate_object_key(key)}"

    async def _send(self, method: str, url: str, headers: dict[str, str], body: bytes) -> int:
        payload = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        signed = self.signer.sign_headers(method, url, headers, payload, self._clock())
        try:
            response = await self.http.request(method, url, headers=signed, content=body)
        except httpx.HTTPError as exc:
            raise StorageError(f"{method} to bucket {self.bucket} failed: {type(exc).__name__}") \
                from None
        return response.status_code

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        headers = {"content-type": content_type}
        if self.settings.encrypted:
            headers["x-amz-server-side-encryption"] = "AES256"
        status = await self._send("PUT", self._url(key), headers, data)
        if status >= 300:
            raise StorageError(f"PUT to bucket {self.bucket} returned {status}")

    async def delete(self, key: str) -> None:
        status = await self._send("DELETE", self._url(key), {}, b"")
        if status >= 300 and status != 404:
            raise StorageError(f"DELETE in bucket {self.bucket} returned {status}")

    def signed_url(self, key: str, ttl_seconds: int = DEFAULT_SIGNED_URL_TTL) -> str:
        return self.signer.presign(
            "GET", self._url(key, public=True), check_ttl(ttl_seconds), self._clock()
        )

    async def aclose(self) -> None:
        await self.http.aclose()


class InMemoryObjectStore:
    """For tests and storage-less local runs. Signs URLs exactly like :class:`S3ObjectStore`
    against a placeholder host, so TTL and key rules are exercised identically."""

    def __init__(self, bucket: str = "test-bucket", clock: Any = _utc_now) -> None:
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_next_put = False
        self._signer = SigV4Signer("in-memory", "in-memory-secret")
        self._clock = clock

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        validate_object_key(key)
        if self.fail_next_put:
            self.fail_next_put = False
            raise StorageError(f"PUT to bucket {self.bucket} returned 503")
        self.objects[key] = (data, content_type)

    async def delete(self, key: str) -> None:
        self.objects.pop(validate_object_key(key), None)

    def signed_url(self, key: str, ttl_seconds: int = DEFAULT_SIGNED_URL_TTL) -> str:
        url = f"http://objects.invalid/{self.bucket}/{validate_object_key(key)}"
        return self._signer.presign("GET", url, check_ttl(ttl_seconds), self._clock())
