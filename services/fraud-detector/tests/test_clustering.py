"""Tests for bid-ring clustering (#55, Plan 6)."""

from uuid import UUID
from app.clustering import RingClusterer


def test_independent_bidders_no_cluster():
    clusterer = RingClusterer(min_cluster_size=2)
    ring1 = clusterer.observe("bidder-1", "seller-1", "fp-1")
    assert ring1 is None

    ring2 = clusterer.observe("bidder-2", "seller-2", "fp-2")
    assert ring2 is None


def test_shared_fingerprint_forms_cluster():
    clusterer = RingClusterer(min_cluster_size=2)
    # Bidder 1 and 2 share device fingerprint fp-alpha
    clusterer.observe("bidder-1", "seller-1", "fp-alpha")
    ring2 = clusterer.observe("bidder-2", "seller-1", "fp-alpha")

    assert ring2 is not None
    assert isinstance(ring2, UUID)

    # Both bidders are in the same ring
    assert clusterer.ring_for_bidder("bidder-1") == ring2
    assert clusterer.ring_for_bidder("bidder-2") == ring2

    members = clusterer.ring_members(ring2)
    assert members == {"bidder-1", "bidder-2"}

    summary = clusterer.ring_summary(ring2)
    assert summary["member_count"] == 2
    assert summary["shared_fingerprints"] == ["fp-alpha"]
    assert summary["confidence"] >= 0.90


def test_third_member_joins_cluster():
    clusterer = RingClusterer(min_cluster_size=2)
    clusterer.observe("bidder-1", "seller-1", "fp-alpha")
    ring_ab = clusterer.observe("bidder-2", "seller-1", "fp-alpha")

    # Bidder 3 shares another fingerprint with bidder 2
    ring_abc = clusterer.observe("bidder-3", "seller-2", "fp-alpha")
    assert ring_abc is not None
    assert clusterer.ring_members(ring_abc) == {"bidder-1", "bidder-2", "bidder-3"}
