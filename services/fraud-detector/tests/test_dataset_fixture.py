"""The checked-in dataset is exactly what the seeded generator produces (#51)."""

import csv
import gzip
from pathlib import Path

from dataset.generator import EVENTS_FILE, LABELS_FILE, digest, events_jsonl, generate, labels_csv

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fraud"
EVENTS_SHA256 = "a0d3149c9f121db51265fb59fc5c0bfa828fcc7e8fd894680901ba4eb0579c57"
LABELS_SHA256 = "c6e864e267f9e6cc0a97b23bd3476bec3d718799d4ec4ebff5efc48cecc12e0a"


def test_fixture_matches_the_published_digests():
    events = gzip.decompress((FIXTURES / EVENTS_FILE).read_bytes())
    labels = (FIXTURES / LABELS_FILE).read_bytes()
    assert digest(events) == EVENTS_SHA256
    assert digest(labels) == LABELS_SHA256


def test_fixture_is_reproduced_from_its_seed():
    dataset = generate()
    assert digest(events_jsonl(dataset)) == EVENTS_SHA256
    assert digest(labels_csv(dataset)) == LABELS_SHA256


def test_fixture_has_200_rings_over_500_auctions():
    with (FIXTURES / LABELS_FILE).open(newline="") as handle:
        labels = list(csv.DictReader(handle))
    assert len({row["ring_id"] for row in labels}) == 200
    events = gzip.decompress((FIXTURES / EVENTS_FILE).read_bytes()).decode().splitlines()
    assert len({line.split('"auction_id":"')[1][:36] for line in events}) == 500


def test_readme_quotes_the_same_digests():
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    assert EVENTS_SHA256 in readme and LABELS_SHA256 in readme
