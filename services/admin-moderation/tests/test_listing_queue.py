"""Tests for listing moderation queue (#81, Plan 6)."""

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
    bearer,
)
from zeo_common.audit import InMemoryAuditWriter


@pytest.fixture
def test_setup():
    repo = InMemoryAdminRepository()
    audit = InMemoryAuditWriter()
    app = build_app(
        SETTINGS,
        repo,
        audit_writer=audit,
        jwt_settings=JWT,
        clock=lambda: NOW,
    )
    client = TestClient(app)
    return client, repo, audit


def test_user_reports_listing_and_admin_reviews(test_setup):
    client, repo, audit = test_setup
    auction_id = uuid4()

    # User reports listing
    rep_res = client.post(
        "/api/v1/admin/listings/report",
        json={"auction_id": str(auction_id), "reason": "Prohibited item"},
        headers=bearer(USER1, role="USER"),
    )
    assert rep_res.status_code == 201
    review_id = UUID(rep_res.json()["id"])

    # Admin checks queue
    queue_res = client.get("/api/v1/admin/listings/review", headers=bearer(ADMIN, role="ADMIN"))
    assert queue_res.status_code == 200
    queue = queue_res.json()
    assert len(queue) == 1
    assert queue[0]["id"] == str(review_id)
    assert queue[0]["state"] == "PENDING"

    # Admin approves listing
    app_res = client.post(
        f"/api/v1/admin/listings/{review_id}/approve",
        json={"note": "Verified item complies with rules"},
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert app_res.status_code == 200
    assert app_res.json()["state"] == "APPROVED"

    # Queue is now empty
    q2 = client.get("/api/v1/admin/listings/review", headers=bearer(ADMIN, role="ADMIN"))
    assert len(q2.json()) == 0

    # Audited
    audit_entries = audit.for_target("auction", auction_id)
    assert any(e.action == "LISTING_APPROVE" for e in audit_entries)


def test_admin_removes_reported_listing(test_setup):
    client, repo, audit = test_setup
    auction_id = uuid4()

    rep_res = client.post(
        "/api/v1/admin/listings/report",
        json={"auction_id": str(auction_id), "reason": "Counterfeit watch"},
        headers=bearer(USER1, role="USER"),
    )
    review_id = UUID(rep_res.json()["id"])

    # Admin removes listing
    rem_res = client.post(
        f"/api/v1/admin/listings/{review_id}/remove",
        json={"reason": "COUNTERFEIT", "note": "Confirmed counterfeit logo"},
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert rem_res.status_code == 200
    assert rem_res.json()["state"] == "REMOVED"

    # Audited
    audit_entries = audit.for_target("auction", auction_id)
    assert any(e.action == "LISTING_REMOVE" for e in audit_entries)
