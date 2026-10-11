from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import fmean

import pytest

from app.features import FeatureExtractor, bids_per_minute, interarrival_cv
from dataset.generator import DatasetConfig, generate

START = datetime(2026, 9, 1, tzinfo=UTC)
SMALL = DatasetConfig(n_auctions=60, n_rings=20, n_honest_accounts=200, n_clean_sellers=15,
                      min_clean_auctions=15)


def event(seq, bidder, *, auction="a1", seller="s1", seconds=0.0, fingerprint=None, **extra):
    at = (START + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    return {"schema_version": 1, "auction_id": auction, "bidder_id": bidder,
            "seller_id": seller, "server_seq": seq, "accepted_at": at,
            "device_fingerprint": fingerprint, "amount": "10.00"} | extra


def test_velocity_and_regularity_of_one_bidder():
    extractor = FeatureExtractor()
    for seq in range(1, 6):
        features = extractor.observe(event(seq, "b1", seconds=seq * 10))
    assert features.bids_in_auction == 5
    assert features.bids_per_minute == pytest.approx(6.0)  # every 10 s
    assert features.interarrival_cv == pytest.approx(0.0)  # perfectly regular
    assert features.share_of_auction == 1.0


def test_irregular_gaps_have_a_high_cv():
    times = [START + timedelta(seconds=s) for s in (0, 1, 60, 61, 300)]
    assert interarrival_cv(times) > 1.0
    assert interarrival_cv(times[:2]) is None
    assert bids_per_minute(times[:1]) == 0.0
    assert bids_per_minute([START, START]) == 60.0  # same instant: capped, not infinite
    assert interarrival_cv([START, START, START]) == 0.0


def test_seller_link_ratio_spans_auctions():
    extractor = FeatureExtractor()
    extractor.observe(event(1, "loyal", auction="a1", seller="s1"))
    extractor.observe(event(1, "loyal", auction="a2", seller="s1"))
    linked = extractor.observe(event(2, "loyal", auction="a2", seller="s1"))
    assert linked.seller_link_ratio == 1.0
    mixed = extractor.observe(event(1, "loyal", auction="a3", seller="s2"))
    assert mixed.seller_link_ratio == pytest.approx(0.25)


def test_fingerprint_sharers_count_other_accounts():
    extractor = FeatureExtractor()
    extractor.observe(event(1, "b1", fingerprint="fp_x"))
    extractor.observe(event(2, "b2", fingerprint="fp_x"))
    third = extractor.observe(event(3, "b3", fingerprint="fp_x"))
    assert third.fingerprint_sharers == 2
    loner = extractor.observe(event(4, "b4", fingerprint="fp_y"))
    assert loner.fingerprint_sharers == 0
    unknown = extractor.observe(event(5, "b5"))
    assert unknown.fingerprint_sharers == 0


def test_redelivered_and_unknown_events_are_ignored():
    extractor = FeatureExtractor()
    assert extractor.observe(event(1, "b1")) is not None
    assert extractor.observe(event(1, "b1")) is None
    assert extractor.observe(event(2, "b1", schema_version=2)) is None
    assert extractor.observe(event(2, "b1")).bids_in_auction == 2


def test_windows_are_bounded_and_closed_auctions_forgotten():
    extractor = FeatureExtractor(window_bids=3)
    for seq in range(1, 20):
        extractor.observe(event(seq, "b1", seconds=seq))
    assert len(extractor._recent[("a1", "b1")]) == 3
    extractor.forget_auction("a1")
    assert extractor._recent == {}
    fresh = extractor.observe(event(1, "b1", seconds=100))
    assert fresh.bids_in_auction == 1
    assert fresh.seller_link_ratio == 1.0  # cross-auction history survives


def test_the_window_needs_three_bids():
    with pytest.raises(ValueError):
        FeatureExtractor(window_bids=2)


def test_features_separate_rings_from_honest_bidders_on_the_labelled_dataset():
    dataset = generate(SMALL)
    shills = {(str(label.auction_id), str(label.bidder_id)) for label in dataset.labels}
    extractor = FeatureExtractor()
    latest = {}
    for item in sorted(dataset.events, key=lambda e: (e["auction_id"], e["server_seq"])):
        features = extractor.observe(item)
        latest[(features.auction_id, features.bidder_id)] = features
    groups = defaultdict(list)
    for key, features in latest.items():
        groups[key in shills].append(features)
    ring, honest = groups[True], groups[False]
    assert ring and honest
    assert fmean(f.seller_link_ratio for f in ring) > fmean(f.seller_link_ratio for f in honest)
    assert fmean(f.fingerprint_sharers for f in ring) > fmean(
        f.fingerprint_sharers for f in honest)
