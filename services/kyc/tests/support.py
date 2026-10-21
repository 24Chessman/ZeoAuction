from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.adapters.kyc_repo import InMemoryKycRepository
from app.domain.aadhaar import load_trusted_key
from app.domain.face import FaceReading, ReferenceFace
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


def frame(n: int) -> bytes:
    """A distinct synthetic JPEG frame (distinct bytes, so not a replayed duplicate)."""
    return JPEG + f"frame-{n}".encode()


def frames(count: int = 3) -> list[bytes]:
    return [frame(n) for n in range(count)]


def qr_text(holder: Holder | None = None, *, generated_at: datetime | None = None,
            identity: SigningIdentity = IDENTITY, version: int = 2,
            photo: bytes = JP2) -> str:
    return make_qr_text(identity, photo, holder=holder, version=version,
                        generated_at=generated_at or datetime.now(UTC))


def qr_image(holder: Holder | None = None, **kwargs) -> bytes:
    """A PNG of a synthetic Secure QR, as the seller would upload it."""
    return qr_png(qr_text(holder, **kwargs))


def readings(*scores: float, yaws: tuple[float, ...] = (-0.2, 0.0, 0.2)) -> list[FaceReading]:
    return [FaceReading(faces=1, score=score, yaw=yaws[i % len(yaws)])
            for i, score in enumerate(scores)]


class FakeFaceEngine:
    """Scripted engine: the reference photo always has one face unless told otherwise, and
    ``compare`` returns ``next_readings`` (a clear match by default)."""

    model = "fake-engine"

    def __init__(self) -> None:
        self.reference_faces = 1
        self.decodable = True
        self.next_readings: list[FaceReading] | None = None
        self.compared: list[tuple[tuple[float, ...] | None, int]] = []

    def reference(self, photo: bytes) -> ReferenceFace:
        if not self.decodable:
            return ReferenceFace(jpeg=None, faces=0, embedding=None)
        embedding = (1.0, 0.0, 0.0) if self.reference_faces == 1 else None
        return ReferenceFace(jpeg=JPEG + b"aadhaar", faces=self.reference_faces,
                             embedding=embedding)

    def compare(self, embedding, frames_: list[bytes]) -> list[FaceReading]:
        self.compared.append((embedding, len(frames_)))
        if self.next_readings is not None:
            return self.next_readings
        return readings(*([0.6] * len(frames_)))


def bearer(user_id: UUID, role: str = "USER", kyc_status: str = "NOT_SUBMITTED") -> dict:
    token = encode_access_token(JWT, user_id=user_id, role=role, kyc_status=kyc_status,
                                suspended=False)
    return {"Authorization": f"Bearer {token}"}


class Harness:
    def __init__(self) -> None:
        self.repo = InMemoryKycRepository()
        self.store = InMemoryObjectStore("kyc-documents")
        self.versions = InMemoryTokenVersions()
        self.engine = FakeFaceEngine()
        self.app = build_app(SETTINGS, repository=self.repo, store=self.store,
                             token_versions=self.versions, jwt_settings=JWT,
                             face_engine=self.engine, trusted_keys=[TRUSTED])
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

    def face(self, user_id: UUID, submission_id: str, images: list[bytes] | None = None):
        files = [("frames", (f"f{i}.jpg", data, "image/jpeg"))
                 for i, data in enumerate(images if images is not None else frames())]
        return self.client.post(f"/api/v1/kyc/submissions/{submission_id}/face", files=files,
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
        """A seller whose Aadhaar verified and who now waits for the face check."""
        user_id = user_id or uuid4()
        response = self.upload(user_id)
        assert response.status_code == 201, response.text
        return user_id, response.json()["submission_id"]

    def in_review(self, user_id: UUID | None = None) -> tuple[UUID, str]:
        """A seller whose face check was borderline, so an administrator decides."""
        user_id, submission_id = self.submitted(user_id)
        self.engine.next_readings = readings(0.35, 0.36, 0.34)
        response = self.face(user_id, submission_id)
        self.engine.next_readings = None
        assert response.json()["outcome"] == "REVIEW", response.text
        return user_id, submission_id
