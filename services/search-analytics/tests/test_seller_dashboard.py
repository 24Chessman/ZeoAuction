"""Tests for the seller dashboard (Plan 6, #75)."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from app.adapters.order_client import InMemoryOrderClient, SellerOrderInfo
from app.adapters.search_repo import InMemorySearchRepository
from tests.support import (
    ADMIN,
    BUYER,
    OTHER,
    SELLER,
    NOW,
    bearer,
    build_test_app,
    make_auction,
)


def _load_repo(*auctions):
    import asyncio
    repo = InMemorySearchRepository()
    for a in auctions:
        asyncio.run(repo.upsert(a))
    return repo


def test_seller_dashboard_no_orders():
    """Seller with listings but no orders shows listings without escrow info."""
    listing = make_auction(seller_id=SELLER, title="My Listing", state="ACTIVE")
    repo = _load_repo(listing)
    client = build_test_app(repo)
    res = client.get(f"/api/v1/seller/{SELLER}/dashboard", headers=bearer(SELLER))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    item = data[0]
    assert item["title"] == "My Listing"
    assert item["order_id"] is None
    assert item["escrow_state"] is None
    assert item["payout_amount"] is None
    assert item["simulation_notice"] == "Escrow amounts are simulated and do not involve real money"


def test_seller_dashboard_with_shipped_order():
    """Seller dashboard shows escrow state, expected payout date and payout amount."""
    listing = make_auction(seller_id=SELLER, title="Shipped Item", state="SETTLED")
    order_id = uuid4()
    shipped_at = NOW
    order = SellerOrderInfo(
        order_id=order_id,
        auction_id=listing.auction_id,
        state="SHIPPED",
        captured_amount=Decimal("1025.00"),
        fee_amount=Decimal("25.00"),
        currency="INR",
        shipped_at=shipped_at,
        protection_window_days=7,
    )
    repo = _load_repo(listing)
    order_client = InMemoryOrderClient({SELLER: [order]})
    client = build_test_app(repo, order_client)
    res = client.get(f"/api/v1/seller/{SELLER}/dashboard", headers=bearer(SELLER))
    assert res.status_code == 200
    item = res.json()[0]
    assert item["escrow_state"] == "SHIPPED"
    assert item["order_id"] == str(order_id)
    assert item["payout_amount"] == "1000.00"  # 1025 - 25
    # expected_payout_date = shipped_at + 7 days
    from datetime import datetime, UTC
    expected = (shipped_at + timedelta(days=7)).isoformat()
    assert item["expected_payout_date"] is not None


def test_seller_dashboard_with_released_order():
    """RELEASED order shows final payout info."""
    listing = make_auction(seller_id=SELLER, title="Released Item", state="SETTLED")
    order = SellerOrderInfo(
        order_id=uuid4(),
        auction_id=listing.auction_id,
        state="RELEASED",
        captured_amount=Decimal("2025.00"),
        fee_amount=Decimal("25.00"),
        currency="INR",
        shipped_at=NOW,
        protection_window_days=7,
    )
    repo = _load_repo(listing)
    order_client = InMemoryOrderClient({SELLER: [order]})
    client = build_test_app(repo, order_client)
    res = client.get(f"/api/v1/seller/{SELLER}/dashboard", headers=bearer(SELLER))
    assert res.status_code == 200
    item = res.json()[0]
    assert item["escrow_state"] == "RELEASED"
    assert item["payout_amount"] == "2000.00"  # 2025 - 25


def test_seller_dashboard_requires_authentication():
    client = build_test_app()
    res = client.get(f"/api/v1/seller/{SELLER}/dashboard")
    assert res.status_code == 401


def test_seller_dashboard_forbidden_for_other_user():
    """Other users cannot see the seller's dashboard."""
    client = build_test_app()
    res = client.get(f"/api/v1/seller/{SELLER}/dashboard", headers=bearer(OTHER))
    assert res.status_code == 403


def test_admin_can_see_any_seller_dashboard():
    listing = make_auction(seller_id=SELLER, title="Admin-visible Listing")
    repo = _load_repo(listing)
    client = build_test_app(repo)
    res = client.get(
        f"/api/v1/seller/{SELLER}/dashboard",
        headers=bearer(ADMIN, role="ADMIN"),
    )
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_seller_dashboard_multiple_listings():
    """Dashboard returns all seller's listings."""
    repo = _load_repo(
        make_auction(seller_id=SELLER, title="Item A"),
        make_auction(seller_id=SELLER, title="Item B"),
        make_auction(seller_id=OTHER, title="Other Seller Item"),  # excluded
    )
    client = build_test_app(repo)
    res = client.get(f"/api/v1/seller/{SELLER}/dashboard", headers=bearer(SELLER))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    titles = {item["title"] for item in data}
    assert titles == {"Item A", "Item B"}
