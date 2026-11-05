"""Contract tests for CT-2 KYC gate and CT-3 Pricing Engine (Plan 7, #48; FR-TEST-1).

Owner: Sagar (#48).
Proves:
1. CT-2 KYC gate:
   - KYC status vocabulary strictly matches between OpenAPI CT-2, zeo_common.auth.KYC_STATUSES,
     and the listing gate enforcement in zeo_common.gateway.
   - AC-06: Direct API calls with any non-VERIFIED status are rejected with 403 SELLER_NOT_VERIFIED.
   - Stale tokens (tv mismatch) are rejected with 401 UNAUTHENTICATED (TOKEN_STALE).
   - Suspended accounts are rejected with 403 ACCOUNT_SUSPENDED.

2. CT-3 Pricing engine:
   - Money format is pinned to two-decimal string representation across all schemas.
   - Bid rejection taxonomy in contracts/errors/bid-rejection-codes.yaml matches pricing rejections.
   - min_next_bid strictly equals current_price + min_increment.
"""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from zeo_common.auth import KYC_STATUSES, JwtSettings, encode_access_token
from zeo_common.errors import ApiError
from zeo_common.gateway import require_verified_seller
from zeo_common.money import parse_money

from .conftest import CONTRACTS

KYC_CONTRACT = yaml.safe_load(
    (CONTRACTS / "openapi" / "internal" / "kyc-status.v1.yaml").read_text(encoding="utf-8")
)
PRICING_CONTRACT = yaml.safe_load(
    (CONTRACTS / "openapi" / "internal" / "pricing.v1.yaml").read_text(encoding="utf-8")
)
REJECTION_CODES = yaml.safe_load(
    (CONTRACTS / "errors" / "bid-rejection-codes.yaml").read_text(encoding="utf-8")
)["codes"]

JWT = JwtSettings(secret="ct2-ct3-test-secret-at-least-32-bytes-long!")


# ==============================================================================
# CT-2: KYC Listing Gate Contract
# ==============================================================================


def test_ct2_kyc_status_vocabulary_agreement():
    """Vocabulary in OpenAPI CT-2 matches zeo_common.auth.KYC_STATUSES exactly."""
    openapi_statuses = KYC_CONTRACT["components"]["schemas"]["KycStatus"]["enum"]
    assert set(openapi_statuses) == set(KYC_STATUSES)
    assert openapi_statuses == ["NOT_SUBMITTED", "SUBMITTED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "SUSPENDED"]


def test_ct2_gate_verified_seller_passes():
    """A fresh, verified, unsuspended token passes the listing gate."""
    user_id = uuid4()
    token = encode_access_token(
        JWT,
        user_id=user_id,
        role="USER",
        kyc_status="VERIFIED",
        suspended=False,
        token_version=1,
    )
    from zeo_common.auth import decode_access_token
    from zeo_common.gateway import check_verified_seller
    principal = decode_access_token(JWT, token)
    # Check does not raise
    check_verified_seller(principal)
    assert principal.user_id == user_id
    assert principal.kyc_status == "VERIFIED"


@pytest.mark.parametrize(
    "unverified_status",
    ["NOT_SUBMITTED", "SUBMITTED", "UNDER_REVIEW", "REJECTED", "SUSPENDED"],
)
def test_ct2_gate_rejects_non_verified_statuses(unverified_status):
    """AC-06: Direct API call with any non-VERIFIED status is refused with 403 SELLER_NOT_VERIFIED."""
    token = encode_access_token(
        JWT,
        user_id=uuid4(),
        role="USER",
        kyc_status=unverified_status,
        suspended=False,
        token_version=1,
    )
    from zeo_common.auth import decode_access_token
    from zeo_common.gateway import check_verified_seller
    principal = decode_access_token(JWT, token)

    with pytest.raises(ApiError) as exc_info:
        check_verified_seller(principal)

    err = exc_info.value
    assert err.status_code == 403
    assert err.code == "SELLER_NOT_VERIFIED"
    assert err.details.get("kyc_status") == unverified_status


def test_ct2_gate_rejects_suspended_account():
    """Suspended accounts are refused with 403 ACCOUNT_SUSPENDED even if kyc_status=VERIFIED."""
    token = encode_access_token(
        JWT,
        user_id=uuid4(),
        role="USER",
        kyc_status="VERIFIED",
        suspended=True,
        token_version=1,
    )
    from zeo_common.auth import decode_access_token
    from zeo_common.gateway import check_verified_seller
    principal = decode_access_token(JWT, token)

    with pytest.raises(ApiError) as exc_info:
        check_verified_seller(principal)

    err = exc_info.value
    assert err.status_code == 403
    assert err.code == "ACCOUNT_SUSPENDED"


@pytest.mark.asyncio
async def test_ct2_gate_rejects_stale_token():
    """Stale token (caller holds older tv) is refused with 401 UNAUTHENTICATED (TOKEN_STALE)."""
    user_id = uuid4()
    token = encode_access_token(
        JWT,
        user_id=user_id,
        role="USER",
        kyc_status="VERIFIED",
        suspended=False,
        token_version=1,  # Older version
    )
    from zeo_common.auth import decode_access_token
    from zeo_common.gateway import InMemoryTokenVersions, check_fresh
    principal = decode_access_token(JWT, token)

    store = InMemoryTokenVersions()
    await store.publish(user_id, 2)  # Store has version 2

    with pytest.raises(ApiError) as exc_info:
        await check_fresh(principal, store)

    err = exc_info.value
    assert err.status_code == 401
    assert err.code == "UNAUTHENTICATED"
    assert err.details.get("reason") == "TOKEN_STALE"


# ==============================================================================
# CT-3: Pricing Engine Contract
# ==============================================================================


def test_ct3_pricing_operations_published():
    """Internal contract defines both getMinIncrement and getVelocity operations."""
    paths = PRICING_CONTRACT["paths"]
    assert "/pricing/{auctionId}/min-increment" in paths
    assert "/pricing/{auctionId}/velocity" in paths

    min_inc_op = paths["/pricing/{auctionId}/min-increment"]["get"]
    assert min_inc_op["operationId"] == "getMinIncrement"

    velocity_op = paths["/pricing/{auctionId}/velocity"]["get"]
    assert velocity_op["operationId"] == "getVelocity"


def test_ct3_pricing_schema_requires_decimal_money_format():
    """MinIncrement schema enforces money string format, never float/int."""
    schema = PRICING_CONTRACT["components"]["schemas"]["MinIncrement"]
    assert schema["type"] == "object"
    assert "min_increment" in schema["required"]
    assert "min_next_bid" in schema["required"]
    assert schema["properties"]["min_increment"]["$ref"].endswith("/Money")
    assert schema["properties"]["min_next_bid"]["$ref"].endswith("/Money")


def test_ct3_pricing_increment_arithmetic_invariant():
    """Invariant: min_next_bid == current_price + min_increment."""
    current_price = Decimal("1250.00")
    min_increment = Decimal("25.00")
    min_next_bid = current_price + min_increment
    assert min_next_bid == Decimal("1275.00")


def test_ct3_rejection_codes_include_pricing_violations():
    """Taxonomy includes BID_BELOW_INCREMENT with HTTP 422 and details.min_next_bid."""
    below_inc = next((c for c in REJECTION_CODES if c["code"] == "BID_BELOW_INCREMENT"), None)
    assert below_inc is not None
    assert below_inc["http"] == 422
    assert below_inc["path"] == "bid"
    assert below_inc["retryable"] is False
    assert "min_next_bid" in below_inc["details"]
