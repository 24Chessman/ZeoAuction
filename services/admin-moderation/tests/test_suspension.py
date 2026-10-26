"""Tests for user suspension workflow (#82, Plan 6)."""

from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from app.adapters.admin_repo import InMemoryAdminRepository
from app.main import build_app
from tests.support import (
    ADMIN,
    JWT,
    NOW,
    SETTINGS,
    USER1,
    USER2,
    bearer,
)
from zeo_common.audit import InMemoryAuditWriter


class FakeTokenPublisher:
    def __init__(self) -> None:
        self.bumped: list[UUID] = []

    async def bump_version(self, user_id: UUID) -> int:
        self.bumped.append(user_id)
        return 2

    async def version_for(self, user_id: UUID) -> int:
        return 2 if user_id in self.bumped else 1


@pytest.fixture
def test_setup():
    repo = InMemoryAdminRepository()
    audit = InMemoryAuditWriter()
    tokens = FakeTokenPublisher()
    app = build_app(
        SETTINGS,
        repo,
        audit_writer=audit,
        token_publisher=tokens,
        jwt_settings=JWT,
        clock=lambda: NOW,
    )
    client = TestClient(app)
    return client, repo, audit, tokens


def test_admin_suspend_user_with_reason_and_audit(test_setup):
    client, repo, audit, tokens = test_setup
    target_user = USER1

    res = client.post(
        f"/api/v1/admin/users/{target_user}/suspend",
        json={"reason_code": "SHILL_BIDDING", "note": "Coordinated bidding ring detected"},
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == str(target_user)
    assert data["reason_code"] == "SHILL_BIDDING"
    assert data["is_active"] is True

    # Token version bumped to force refresh
    assert target_user in tokens.bumped

    # Audited in admin.audit_log
    audit_entries = audit.for_target("user", target_user)
    assert len(audit_entries) == 1
    assert audit_entries[0].action == "USER_SUSPEND"
    assert audit_entries[0].reason_code == "SHILL_BIDDING"


def test_suspend_already_suspended_user_conflict(test_setup):
    client, repo, audit, tokens = test_setup
    target_user = USER2

    client.post(
        f"/api/v1/admin/users/{target_user}/suspend",
        json={"reason_code": "FRAUD", "note": "Fraudulent payment attempt"},
        headers=bearer(ADMIN, role="ADMIN"),
    )

    res = client.post(
        f"/api/v1/admin/users/{target_user}/suspend",
        json={"reason_code": "FRAUD", "note": "Second attempt"},
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert res.status_code == 409


def test_non_admin_cannot_suspend(test_setup):
    client, repo, audit, tokens = test_setup
    res = client.post(
        f"/api/v1/admin/users/{USER1}/suspend",
        json={"reason_code": "ABUSIVE_BEHAVIOR", "note": "Spam"},
        headers=bearer(USER2, role="USER"),
    )
    assert res.status_code == 403


def test_admin_reinstate_user(test_setup):
    client, repo, audit, tokens = test_setup
    target_user = USER1

    # Suspend
    client.post(
        f"/api/v1/admin/users/{target_user}/suspend",
        json={"reason_code": "TERMS_VIOLATION", "note": "To be resolved"},
        headers=bearer(ADMIN, role="ADMIN"),
    )

    # Reinstate
    res = client.post(
        f"/api/v1/admin/users/{target_user}/reinstate",
        json={"note": "Identity clarified, reinstatement approved"},
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    # Audited
    audit_entries = audit.for_target("user", target_user)
    assert any(e.action == "USER_REINSTATE" for e in audit_entries)
