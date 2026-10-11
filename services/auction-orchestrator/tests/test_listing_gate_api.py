"""AC-06: the listing gate holds at the API, called directly with a valid token (#41, CT-2).

No UI is involved: every request below is what a script with a stolen-but-valid token for an
unverified account could send. The gate must refuse it and create nothing.
"""

from uuid import UUID, uuid4

import pytest

from tests.support import SELLER, bearer
from zeo_common.contract_testing import assert_matches_contract

UNVERIFIED = UUID("00000000-0000-4000-8000-000000000003")
NOT_VERIFIED = ["NOT_SUBMITTED", "SUBMITTED", "UNDER_REVIEW", "REJECTED", "SUSPENDED"]
CT2 = ("openapi/internal/kyc-status.v1.yaml", "/components/schemas/GateRefusal")


@pytest.mark.parametrize("kyc_status", NOT_VERIFIED)
def test_unverified_token_cannot_create_an_auction(harness, kyc_status):
    response = harness.create(headers=bearer(UNVERIFIED, kyc_status=kyc_status))
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "SELLER_NOT_VERIFIED"
    assert body["details"] == {"kyc_status": kyc_status}
    assert_matches_contract(body, *CT2)
    assert harness.repo.auctions == {}  # zero auctions created
    assert harness.events.events == []


def test_unverified_token_cannot_publish_an_existing_draft(harness):
    auction_id = harness.created()
    response = harness.publish(auction_id, headers=bearer(SELLER, kyc_status="SUSPENDED"))
    assert response.status_code == 403
    assert response.json()["code"] == "SELLER_NOT_VERIFIED"
    assert harness.repo.auctions[UUID(auction_id)].state == "DRAFT"


def test_suspended_account_is_refused_even_when_verified(harness):
    response = harness.create(headers=bearer(SELLER, suspended=True))
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_SUSPENDED"
    assert_matches_contract(response.json(), *CT2)
    assert harness.repo.auctions == {}


def test_no_token_is_unauthenticated(harness):
    response = harness.client.post("/api/v1/auctions", json={})
    assert response.status_code == 401
    assert harness.repo.auctions == {}


def test_forged_token_is_unauthenticated(harness):
    headers = bearer()
    headers["Authorization"] += "tampered"
    assert harness.create(headers=headers).status_code == 401


def test_approval_takes_effect_on_the_next_refreshed_token(harness):
    """Submit KYC -> admin approves -> token refresh -> seller creates an auction (#105)."""
    seller = uuid4()
    # KYC approved: the mirror bumped token_version to 4 and published it.
    harness.versions.versions[seller] = 4
    old = harness.create(headers=bearer(seller, kyc_status="UNDER_REVIEW", token_version=3))
    assert old.status_code == 401
    assert old.json()["details"] == {"reason": "TOKEN_STALE"}
    assert_matches_contract(old.json(), *CT2)
    refreshed = harness.create(headers=bearer(seller, kyc_status="VERIFIED", token_version=4))
    assert refreshed.status_code == 201
    assert refreshed.json()["seller_id"] == str(seller)


def test_suspension_reaches_a_still_valid_verified_token(harness):
    seller = uuid4()
    harness.versions.versions[seller] = 6  # KYC suspended the seller after this token
    response = harness.create(headers=bearer(seller, kyc_status="VERIFIED", token_version=5))
    assert response.status_code == 401
    assert harness.repo.auctions == {}


def test_gate_fails_closed_when_freshness_cannot_be_checked(harness):
    harness.versions.fail = True
    response = harness.create()
    assert response.status_code == 503
    assert harness.repo.auctions == {}
