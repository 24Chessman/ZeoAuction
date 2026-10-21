from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.features import BidderFeatures, FeatureExtractor
from app.scorer import V1_THRESHOLD, V1_WEIGHTS, ShillDetector, ShillScorer
from app.signals import SIGNAL_NAMES, Signals

START = datetime(2026, 10, 5, tzinfo=UTC)
CLOSES = START + timedelta(days=2)


def features(**overrides) -> BidderFeatures:
    base = BidderFeatures(
        auction_id="a1", bidder_id="b1", seller_id="s1", server_seq=1, bids_in_auction=1,
        share_of_auction=0.2, seller_link_ratio=0.2, fingerprint_sharers=0,
        # one bid: no velocity, so the arithmetic below is exact unless a test sets it
        bids_per_minute=0.0, interarrival_cv=None, observed_at=START, auction_closes_at=CLOSES)
    return replace(base, **overrides)


def test_seller_links_alone_never_reach_the_threshold():
    loyal = ShillScorer().score(features(seller_link_ratio=1.0))
    assert loyal.value == 0.5
    assert not loyal.suspect


def test_seller_links_corroborated_by_velocity_or_a_shared_device_are_suspect():
    scorer = ShillScorer()
    fast = scorer.score(features(seller_link_ratio=1.0, bids_per_minute=1.0, bids_in_auction=3))
    shared = scorer.score(features(seller_link_ratio=1.0, fingerprint_overlap=2))
    assert fast.suspect and fast.value == pytest.approx(0.75)
    assert shared.suspect and shared.value == 0.75
    everything = scorer.score(features(seller_link_ratio=1.0, bids_per_minute=1.0,
                                       bids_in_auction=3, fingerprint_overlap=1))
    assert everything.value == 1.0


def test_an_honest_bidding_war_is_fast_but_not_seller_linked():
    war = ShillScorer().score(features(seller_link_ratio=0.1, bids_per_minute=3.0,
                                       bids_in_auction=8))
    assert war.value < V1_THRESHOLD


def test_a_single_bid_has_no_velocity():
    signals = Signals.from_features(features(bids_in_auction=1, bids_per_minute=60.0))
    assert signals.strengths()["bidVelocity"] == 0.0


def test_every_signal_strength_is_between_zero_and_one():
    for extreme in (
        features(),
        features(bids_per_minute=1e6, seller_link_ratio=1.0, interarrival_cv=0.0,
                 fingerprint_overlap=50, account_age_days=0.0, win_rate_with_seller=0.0,
                 sellers_bid_with=1),
        features(bids_per_minute=0.0, interarrival_cv=9.0, account_age_days=400.0,
                 win_rate_with_seller=1.0, sellers_bid_with=40),
    ):
        strengths = Signals.from_features(extreme).strengths()
        assert set(strengths) == set(SIGNAL_NAMES)
        assert all(0.0 <= value <= 1.0 for value in strengths.values())


def test_evidence_uses_contract_names_and_leaves_out_unknowns():
    evidence = Signals.from_features(features(interarrival_stdev=None)).evidence()
    assert set(evidence) <= set(SIGNAL_NAMES)
    assert "interArrivalStdDev" not in evidence and "winRateWithSeller" not in evidence
    full = Signals.from_features(features(interarrival_stdev=2.5, win_rate_with_seller=0.0))
    assert full.evidence()["interArrivalStdDev"] == 2.5
    assert full.evidence()["winRateWithSeller"] == 0.0


@pytest.mark.parametrize("weights, threshold", [
    ({"madeUp": 1.0}, 0.6),
    ({"bidVelocity": -1.0, "selfBidRatio": 2.0}, 0.6),
    ({"bidVelocity": 0.0}, 0.6),
    (V1_WEIGHTS, 0.0),
    (V1_WEIGHTS, 1.5),
])
def test_bad_configuration_is_refused(weights, threshold):
    with pytest.raises(ValueError):
        ShillScorer(weights, threshold)


def test_the_detector_asks_for_an_alert_once_per_new_suspect():
    detector = ShillDetector()
    shill = dict(seller_link_ratio=1.0, fingerprint_overlap=1)
    assert detector.observe(features(bidder_id="honest")) is None
    first = detector.observe(features(bidder_id="s1", **shill))
    assert first.suspects == ("s1",) and first.score == 0.75
    assert first.auction_closes_at == CLOSES and first.observed_at == START
    assert detector.observe(features(bidder_id="s1", bids_per_minute=2.0, bids_in_auction=3,
                                     **shill)) is None
    second = detector.observe(features(bidder_id="s2", **shill))
    assert second.suspects == ("s1", "s2")
    assert second.score == 1.0  # s1's later, higher score is remembered
    assert detector.suspects("a1") == {"s1": 1.0, "s2": 0.75}
    detector.forget_auction("a1")
    assert detector.suspects("a1") == {}


def test_a_ring_is_flagged_while_its_auction_is_still_open():
    extractor, detector = FeatureExtractor(), ShillDetector()
    closes = (CLOSES).isoformat().replace("+00:00", "Z")
    decisions = []
    for seq, (bidder, minute) in enumerate(
            [("ring1", 0), ("ring2", 1), ("ring1", 2), ("ring2", 3), ("ring1", 4)], start=1):
        at = (START + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")
        event = {"schema_version": 1, "auction_id": "a1", "bidder_id": bidder,
                 "seller_id": "s1", "server_seq": seq, "accepted_at": at,
                 "auction_closes_at": closes, "device_fingerprint": "fp_ring"}
        decision = detector.observe(extractor.observe(event))
        if decision:
            decisions.append(decision)
    assert [d.suspects for d in decisions] == [("ring2",), ("ring2", "ring1")]
    assert all(d.observed_at < d.auction_closes_at for d in decisions)
