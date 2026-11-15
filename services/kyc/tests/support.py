from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.adapters.kyc_repo import InMemoryKycRepository
from app.domain.aadhaar import load_trusted_key
from app.main import build_app
from app.settings import Settings
from scripts.synthetic_qr import Holder, SigningIdentity, make_identity, make_qr_text, qr_png
from zeo_common.auth import JwtSettings, encode_access_token
from zeo_common.gateway import InMemoryTokenVersions
from zeo_common.storage import InMemoryObjectStore

JWT = JwtSettings(secret="kyc-test-secret-at-least-32-bytes!!")
SETTINGS = Settings(
    database_url="unused", redis_url="unused", repository="memory", storage="memory",
    signed_url_ttl_seconds=60, retention_days=365, max_frame_bytes=1024,
)

# Synthetic images: just the format signatures plus filler, never a real face or document.
JP2 = b"\x00\x00\x00\x0cjP  \r\n\x87\n" + b"synthetic-aadhaar-photo"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
# One signing identity per test run: RSA key generation is the slow part.
IDENTITY: SigningIdentity = make_identity()
TRUSTED = load_trusted_key(IDENTITY.certificate)


def qr_text(holder: Holder | None = None, *, generated_at: datetime | None = None,
            identity: SigningIdentity = IDENTITY, version: int = 2,
            photo: bytes = JP2) -> str:
    return make_qr_text(identity, photo, holder=holder, version=version,
                        generated_at=generated_at or datetime.now(UTC))


def qr_image(holder: Holder | None = None, **kwargs) -> bytes:
    """A PNG of a synthetic Secure QR, as the seller would upload it."""
    return qr_png(qr_text(holder, **kwargs))


def bearer(user_id: UUID, role: str = "USER", kyc_status: str = "NOT_SUBMITTED") -> dict:
    token = encode_access_token(JWT, user_id=user_id, role=role, kyc_status=kyc_status,
                                suspended=False)
    return {"Authorization": f"Bearer {token}"}


class Harness:
    def __init__(self) -> None:
        self.repo = InMemoryKycRepository()
        self.store = InMemoryObjectStore("kyc-documents")
        self.versions = InMemoryTokenVersions()
        self.app = build_app(SETTINGS, repository=self.repo, store=self.store,
                             token_versions=self.versions, jwt_settings=JWT,
                             trusted_keys=[TRUSTED])
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.admin = uuid4()

    @property
    def service(self):
        return self.app.state.kyc_service

    def upload(self, user_id: UUID, image: bytes | None = None, *,
               mobile: str | None = None):
        data = {} if mobile is None else {"mobile": mobile}
        files = {"qr_image": ("aadhaar-qr.png", image if image is not None else qr_image(),
                              "image/png")}
        return self.client.post("/api/v1/kyc/aadhaar", data=data, files=files,
                                headers=bearer(user_id))

    def me(self, user_id: UUID):
        return self.client.get("/api/v1/kyc/submissions/me", headers=bearer(user_id))

    def admin_post(self, path: str, json=None):
        return self.client.post(f"/api/v1/admin/kyc/{path}", json=json,
                                headers=bearer(self.admin, role="ADMIN"))

    def admin_get(self, path: str, **params):
        return self.client.get(f"/api/v1/admin/kyc/{path}", params=params,
                               headers=bearer(self.admin, role="ADMIN"))

    def submitted(self, user_id: UUID | None = None) -> tuple[UUID, str]:
        """A seller whose Aadhaar is verified and awaits administrator review."""
        user_id = user_id or uuid4()
        response = self.upload(user_id)
        assert response.status_code == 201, response.text
        return user_id, response.json()["submission_id"]

    def in_review(self, user_id: UUID | None = None) -> tuple[UUID, str]:
        """A seller whose Aadhaar submission is waiting for an administrator."""
        return self.submitted(user_id)
