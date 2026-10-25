"""Tests for the full-text search and filter API (Plan 6, #46, #47)."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from app.adapters.search_repo import InMemorySearchRepository
from tests.support import (
    INTERNAL,
    NOW,
    SELLER,
    bearer,
    build_test_app,
    make_auction,
)


def _repo_with(*auctions):
    """Return an InMemorySearchRepository pre-loaded with auctions."""
    repo = InMemorySearchRepository()

    async def _load():
        for a in auctions:
            await repo.upsert(a)

    asyncio.run(_load())
    return repo


def test_search_no_filters_returns_all():
    repo = _repo_with(
        make_auction(title="Gold Ring"),
        make_auction(title="Silver Bracelet"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_search_text_filter():
    repo = _repo_with(
        make_auction(title="Gold Ring", description="beautiful gold"),
        make_auction(title="Silver Bracelet", description="shiny silver"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"q": "gold"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Gold Ring"


def test_search_category_filter():
    repo = _repo_with(
        make_auction(title="Laptop", category="Electronics"),
        make_auction(title="Necklace", category="Jewelry"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"category": "Jewelry"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Necklace"


def test_search_price_min_filter():
    repo = _repo_with(
        make_auction(title="Cheap", current_price="100.00"),
        make_auction(title="Expensive", current_price="5000.00"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"price_min": "1000"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Expensive"


def test_search_price_max_filter():
    repo = _repo_with(
        make_auction(title="Cheap", current_price="100.00"),
        make_auction(title="Expensive", current_price="5000.00"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"price_max": "1000"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Cheap"


def test_search_status_filter():
    repo = _repo_with(
        make_auction(title="Open Auction", state="ACTIVE"),
        make_auction(title="Closed Auction", state="CLOSED"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"status": "ACTIVE"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Open Auction"


def test_search_sort_price_asc():
    repo = _repo_with(
        make_auction(title="B", current_price="500.00"),
        make_auction(title="A", current_price="200.00"),
        make_auction(title="C", current_price="800.00"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"sort": "price_asc"})
    assert res.status_code == 200
    items = res.json()["items"]
    prices = [Decimal(item["current_price"]) for item in items]
    assert prices == sorted(prices)


def test_search_sort_price_desc():
    repo = _repo_with(
        make_auction(title="B", current_price="500.00"),
        make_auction(title="A", current_price="200.00"),
        make_auction(title="C", current_price="800.00"),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"sort": "price_desc"})
    assert res.status_code == 200
    items = res.json()["items"]
    prices = [Decimal(item["current_price"]) for item in items]
    assert prices == sorted(prices, reverse=True)


def test_search_sort_ending_soonest():
    t1 = NOW + timedelta(hours=1)
    t2 = NOW + timedelta(hours=5)
    repo = _repo_with(
        make_auction(title="Ending Later", closes_at=t2),
        make_auction(title="Ending Soon", closes_at=t1),
    )
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions", params={"sort": "ending_soonest"})
    assert res.status_code == 200
    items = res.json()["items"]
    assert items[0]["title"] == "Ending Soon"


def test_search_pagination():
    repo = _repo_with(
        *[make_auction(title=f"Item {i}") for i in range(5)]
    )
    client = build_test_app(repo)
    # Page 1 of size 2
    res1 = client.get("/api/v1/search/auctions", params={"page": 1, "page_size": 2})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["total"] == 5
    assert len(data1["items"]) == 2
    assert data1["page"] == 1
    assert data1["page_size"] == 2

    # Page 2
    res2 = client.get("/api/v1/search/auctions", params={"page": 2, "page_size": 2})
    assert res2.status_code == 200
    data2 = res2.json()
    assert len(data2["items"]) == 2
    assert data2["page"] == 2

    # Page 3 (1 item)
    res3 = client.get("/api/v1/search/auctions", params={"page": 3, "page_size": 2})
    assert res3.status_code == 200
    assert len(res3.json()["items"]) == 1


def test_search_invalid_sort_returns_422():
    client = build_test_app()
    res = client.get("/api/v1/search/auctions", params={"sort": "invalid_option"})
    assert res.status_code == 422


def test_search_result_has_flat_fee_notice():
    repo = _repo_with(make_auction(title="Ring"))
    client = build_test_app(repo)
    res = client.get("/api/v1/search/auctions")
    assert res.status_code == 200
    items = res.json()["items"]
    assert items[0]["flat_fee_notice"] == "Flat fee applies on win"


def test_internal_upsert_then_search():
    client = build_test_app()
    auction_id = str(uuid4())
    res = client.post(
        f"/api/v1/internal/auctions/{auction_id}/index",
        json={
            "seller_id": str(SELLER),
            "title": "Rare Painting",
            "description": "A rare 19th century painting",
            "category": "Art",
            "current_price": "25000.00",
            "currency": "INR",
            "state": "ACTIVE",
        },
        headers=INTERNAL,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "indexed"

    # Now search for it
    search_res = client.get("/api/v1/search/auctions", params={"q": "painting"})
    assert search_res.status_code == 200
    assert search_res.json()["total"] == 1
    assert search_res.json()["items"][0]["title"] == "Rare Painting"


def test_internal_upsert_requires_token():
    client = build_test_app()
    auction_id = str(uuid4())
    res = client.post(
        f"/api/v1/internal/auctions/{auction_id}/index",
        json={"seller_id": str(SELLER), "title": "Test", "category": "Art",
              "current_price": "100.00", "currency": "INR", "state": "ACTIVE"},
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert res.status_code == 403


def test_internal_delete_removes_from_index():
    repo = InMemorySearchRepository()
    auction = make_auction(title="To Delete")
    asyncio.run(repo.upsert(auction))

    client = build_test_app(repo)
    res = client.delete(
        f"/api/v1/internal/auctions/{auction.auction_id}/index",
        headers=INTERNAL,
    )
    assert res.status_code == 200

    search_res = client.get("/api/v1/search/auctions")
    assert search_res.json()["total"] == 0
