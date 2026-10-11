from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.adapters.kyc_repo import InMemoryKycRepository
from app.main import build_app
from app.settings import Settings
from zeo_common.auth import JwtSettings, encode_access_token
from zeo_common.gateway import InMemoryTokenVersions
from zeo_common.storage import InMemoryObjectStore

JWT = JwtSettings(secret="kyc-test-secret-at-least-32-bytes!!")
SETTINGS = Settings(
    database_url="unused", redis_url="unused", repository="memory", storage="memory",
    signed_url_ttl_seconds=60, max_document_bytes=1024, retention_days=365,
)

# Synthetic sample documents: just the format signatures plus filler, never real data.
PDF = b"%PDF-1.7\n% synthetic sample\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def bearer(user_id: UUID, role: str = "USER", kyc_status: str = "NOT_SUBMITTED") -> dict:
    token = encode_access_token(JWT, user_id=user_id, role=role, kyc_status=kyc_status,
                                suspended=False)
    return {"Authorization": f"Bearer {token}"}


class Harness:
    def __init__(self) -> None:
        self.repo = InMemoryKycRepository()
        self.store = InMemoryObjectStore("kyc-documents")
        self.versions = InMemoryTokenVersions()
        app = build_app(SETTINGS, repository=self.repo, store=self.store,
                        token_versions=self.versions, jwt_settings=JWT)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.admin = uuid4()

    def submit(self, user_id: UUID, **files):
        files = files or {
            "government_id": ("id.pdf", PDF, "application/pdf"),
            "proof_of_address": ("bill.png", PNG, "image/png"),
        }
        return self.client.post("/api/v1/kyc/submissions", files=files, headers=bearer(user_id))

    def admin_post(self, path: str, json=None):
        return self.client.post(f"/api/v1/admin/kyc/{path}", json=json,
                                headers=bearer(self.admin, role="ADMIN"))

    def admin_get(self, path: str, **params):
        return self.client.get(f"/api/v1/admin/kyc/{path}", params=params,
                               headers=bearer(self.admin, role="ADMIN"))

    def submitted(self, user_id: UUID | None = None) -> tuple[UUID, str]:
        user_id = user_id or uuid4()
        response = self.submit(user_id)
        assert response.status_code == 201, response.text
        return user_id, response.json()["submission_id"]


