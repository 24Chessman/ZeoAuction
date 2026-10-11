from collections import defaultdict
from decimal import Decimal

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dataset.generator import (
    DatasetConfig,
    digest,
    events_jsonl,
    generate,
    labels_csv,
    main,
    summary,
    write,
)
from dataset.patterns import SIGNALS, increment_for, sample_ring_pattern
from zeo_common.contract_testing import contract_schema

SMALL = DatasetConfig(n_auctions=40, n_rings=12, n_honest_accounts=150, n_clean_sellers=10,
                      min_clean_auctions=10)


@pytest.fixture(scope="module")
def full():
    return generate()


def test_same_seed_same_bytes():
    assert events_jsonl(generate(SMALL)) == events_jsonl(generate(SMALL))
    assert labels_csv(generate(SMALL)) == labels_csv(generate(SMALL))


def test_different_seed_different_dataset():
    other = DatasetConfig(**{**SMALL.__dict__, "seed": SMALL.seed + 1})
    assert events_jsonl(generate(other)) != events_jsonl(generate(SMALL))


def test_full_dataset_has_500_auctions_and_200_labelled_rings(full):
    stats = summary(full)
    assert stats["auctions"] == 500
    assert stats["rings"] == 200
    assert stats["shilled_auctions"] + stats["clean_auctions"] == 500
    assert stats["clean_auctions"] >= 100


def test_every_event_is_a_valid_bid_accepted_v1(full):
    validator = Draft202012Validator(contract_schema("events/bid_accepted.v1.json"),
                                     format_checker=FormatChecker())
    for event in full.events:
        validator.validate(event)


def test_each_auction_obeys_the_live_bidding_rules(full):
    by_auction = defaultdict(list)
    for event in full.events:
        by_auction[event["auction_id"]].append(event)
    for events in by_auction.values():
        events.sort(key=lambda e: e["server_seq"])
        assert [e["server_seq"] for e in events] == list(range(1, len(events) + 1))
        for previous, current in zip(events, events[1:], strict=False):
            floor = Decimal(previous["amount"]) + increment_for(Decimal(previous["amount"]))
            assert Decimal(current["amount"]) >= floor
            assert current["accepted_at"] >= previous["accepted_at"]
            assert current["bidder_id"] != previous["bidder_id"]
        assert all(e["accepted_at"] < e["auction_closes_at"] for e in events)
        assert len({e["seller_id"] for e in events}) == 1


def test_sellers_never_bid_and_labels_point_at_real_shill_bids(full):
    pairs = {(e["auction_id"], e["bidder_id"]) for e in full.events}
    assert all(e["bidder_id"] != e["seller_id"] for e in full.events)
    for label in full.labels:
        assert (str(label.auction_id), str(label.bidder_id)) in pairs


def test_rings_only_work_their_own_sellers_auctions(full):
    seller_of = {a.auction_id: a.seller_id for a in full.auctions}
    for label in full.labels:
        assert seller_of[label.auction_id] == label.seller_id


def test_seller_linked_rings_never_bid_elsewhere(full):
    shill_accounts = {str(lb.bidder_id): lb for lb in full.labels if "seller_linked" in lb.signals}
    for event in full.events:
        label = shill_accounts.get(event["bidder_id"])
        if label:
            assert event["seller_id"] == str(label.seller_id)


def test_shared_fingerprint_rings_reuse_devices(full):
    rings = {r.ring_id: r for r in full.rings}
    for ring in rings.values():
        if "shared_fingerprint" in ring.pattern.signals:
            assert len(set(ring.fingerprints)) < len(ring.accounts)


def test_every_signal_appears_and_shills_are_a_minority(full):
    seen = {s for lb in full.labels for s in lb.signals.split("|")}
    assert seen == set(SIGNALS)
    stats = summary(full)
    assert stats["shill_events"] < stats["events"] * 0.35


def test_clean_auctions_contain_look_alikes(full):
    clean = {str(a.auction_id) for a in full.auctions if a.ring is None}
    devices = defaultdict(set)
    for event in full.events:
        if event["auction_id"] in clean and event["device_fingerprint"]:
            devices[(event["auction_id"], event["device_fingerprint"])].add(event["bidder_id"])
    assert any(len(bidders) > 1 for bidders in devices.values())  # households


def test_ring_patterns_always_carry_a_signal():
    import random

    rng = random.Random(1)
    assert all(sample_ring_pattern(rng).signals for _ in range(500))


def test_write_produces_gzip_and_csv_with_matching_digests(tmp_path):
    dataset = generate(SMALL)
    digests = write(dataset, tmp_path)
    import gzip

    events = gzip.decompress((tmp_path / "dataset-v1.jsonl.gz").read_bytes())
    assert digest(events) == digests["dataset-v1.jsonl.gz"]
    labels = (tmp_path / "labels-v1.csv").read_text()
    assert labels.splitlines()[0] == "ring_id,seller_id,auction_id,bidder_id,signals"
    assert digest(labels.encode()) == digests["labels-v1.csv"]


def test_cli_writes_the_files(tmp_path, capsys):
    main(["--out", str(tmp_path)])
    assert (tmp_path / "labels-v1.csv").exists()
    out = capsys.readouterr().out
    assert '"auctions": 500' in out and '"rings": 200' in out
