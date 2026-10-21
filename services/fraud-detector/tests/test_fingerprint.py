from datetime import UTC, datetime, timedelta

from app.features import FeatureExtractor
from app.signals.fingerprint import FingerprintIndex

START = datetime(2026, 10, 5, tzinfo=UTC)


def bid(seq, bidder, *, auction="a1", seller="s1", fingerprint=None, seconds=0):
    at = (START + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    return {"schema_version": 1, "auction_id": auction, "bidder_id": bidder, "seller_id": seller,
            "server_seq": seq, "accepted_at": at, "device_fingerprint": fingerprint}


def test_overlap_counts_only_accounts_on_the_same_device_in_the_same_auction():
    index = FingerprintIndex()
    index.observe("a1", "shill1", "fp_ring")
    index.observe("a1", "shill2", "fp_ring")
    index.observe("a2", "household", "fp_ring")  # same device, another auction
    index.observe("a1", "honest", "fp_own")
    assert index.overlap_in_auction("a1", "shill1") == 1
    assert index.overlap_in_auction("a1", "honest") == 0
    assert index.sharers("shill1") == 2  # the global view sees the household too
    assert index.overlap_in_auction("a2", "household") == 0


def test_every_device_a_bidder_used_in_the_auction_counts():
    index = FingerprintIndex()
    index.observe("a1", "b1", "phone")
    index.observe("a1", "b1", "laptop")
    index.observe("a1", "b2", "laptop")
    index.observe("a1", "b3", "phone")
    assert index.overlap_in_auction("a1", "b1") == 2
    assert index.overlap_in_auction("a1", "b2") == 1


def test_a_missing_fingerprint_is_no_evidence():
    index = FingerprintIndex()
    index.observe("a1", "b1", None)
    index.observe("a1", "b2", "")
    assert index.sharers("b1") == 0
    assert index.overlap_in_auction("a1", "b1") == 0
    assert index.overlap_in_auction("nowhere", "b1") == 0


def test_forgetting_an_auction_keeps_the_cross_auction_index():
    index = FingerprintIndex()
    index.observe("a1", "b1", "fp")
    index.observe("a1", "b2", "fp")
    index.forget_auction("a1")
    assert index.overlap_in_auction("a1", "b1") == 0
    assert index.sharers("b1") == 1
    index.forget_auction("never-seen")


def test_the_extractor_reports_in_auction_overlap_from_the_bid_events():
    extractor = FeatureExtractor()
    extractor.observe(bid(1, "s1", fingerprint="fp_ring"))
    second = extractor.observe(bid(2, "s2", fingerprint="fp_ring", seconds=30))
    assert second.fingerprint_overlap == 1
    assert second.fingerprint_sharers == 1
    elsewhere = extractor.observe(bid(1, "s3", auction="a2", fingerprint="fp_ring"))
    assert elsewhere.fingerprint_overlap == 0
    assert elsewhere.fingerprint_sharers == 2
