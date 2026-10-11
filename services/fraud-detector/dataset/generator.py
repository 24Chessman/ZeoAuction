"""Labelled synthetic dataset: 500 auctions, 200 shill rings (#51, ADR-0008).

Built **before** any detector, so the Section 10 recall and precision can be measured from
the first detector iteration. Output is a seeded, reproducible stream of ``BidAccepted v1``
events (the exact shape on ``bid.events``, so it can be replayed into Kafka) plus a labels
file naming every shill account per auction.

    python -m dataset.generator --out ../../tests/fixtures/fraud

The same seed always produces the same events, byte for byte (before compression).
"""

import argparse
import csv
import gzip
import hashlib
import io
import json
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from dataset.patterns import RingPattern, increment_for, sample_ring_pattern

VERSION = "v1"
EVENTS_FILE = f"dataset-{VERSION}.jsonl.gz"
LABELS_FILE = f"labels-{VERSION}.csv"
LABEL_COLUMNS = ("ring_id", "seller_id", "auction_id", "bidder_id", "signals")
CENTS = Decimal("0.01")


@dataclass(frozen=True)
class DatasetConfig:
    seed: int = 20260904
    n_auctions: int = 500
    n_rings: int = 200
    n_honest_accounts: int = 1500
    n_clean_sellers: int = 120
    min_clean_auctions: int = 100
    start: datetime = datetime(2026, 8, 3, tzinfo=UTC)
    span_days: int = 28
    household_rate: float = 0.06  # honest accounts sharing a device with another
    bidding_war_rate: float = 0.25  # clean look-alike of high velocity
    currency: str = "USD"


@dataclass(frozen=True)
class Ring:
    ring_id: uuid.UUID
    seller_id: uuid.UUID
    pattern: RingPattern
    accounts: tuple[uuid.UUID, ...]
    fingerprints: tuple[str, ...]  # one per account, possibly repeated


@dataclass(frozen=True)
class AuctionPlan:
    auction_id: uuid.UUID
    seller_id: uuid.UUID
    opens_at: datetime
    closes_at: datetime
    starting_price: Decimal
    valuation: Decimal
    ring: Ring | None


@dataclass(frozen=True)
class Label:
    ring_id: uuid.UUID
    seller_id: uuid.UUID
    auction_id: uuid.UUID
    bidder_id: uuid.UUID
    signals: str


@dataclass
class Dataset:
    config: DatasetConfig
    auctions: list[AuctionPlan]
    rings: list[Ring]
    events: list[dict[str, Any]] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)


@dataclass(frozen=True)
class _Attempt:
    at: datetime
    order: int  # tie-break, fixed at creation
    bidder_id: uuid.UUID
    fingerprint: str | None
    ceiling: Decimal  # the most this bidder will pay
    shill: bool


class _Ids:
    """UUIDs drawn from the seeded generator, so ids are reproducible too."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def __call__(self) -> uuid.UUID:
        return uuid.UUID(int=self.rng.getrandbits(128), version=4)

    def fingerprint(self) -> str:
        return f"fp_{self.rng.getrandbits(48):012x}"


def _money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_EVEN)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def generate(config: DatasetConfig | None = None) -> Dataset:
    config = config or DatasetConfig()
    rng = random.Random(config.seed)
    new_id = _Ids(rng)

    # Honest accounts, some sharing a household device (a clean look-alike of a ring).
    honest: list[tuple[uuid.UUID, str]] = []
    for _ in range(config.n_honest_accounts):
        if honest and rng.random() < config.household_rate:
            honest.append((new_id(), honest[-1][1]))
        else:
            honest.append((new_id(), new_id.fingerprint()))
    clean_sellers = [new_id() for _ in range(config.n_clean_sellers)]

    rings: list[Ring] = []
    for _ in range(config.n_rings):
        pattern = sample_ring_pattern(rng)
        pool = [new_id.fingerprint() for _ in range(pattern.fingerprints)]
        rings.append(Ring(
            ring_id=new_id(), seller_id=new_id(), pattern=pattern,
            accounts=tuple(new_id() for _ in range(pattern.size)),
            fingerprints=tuple(pool[i % len(pool)] for i in range(pattern.size)),
        ))

    # Loyal honest buyers who keep coming back to one seller (a look-alike of seller links).
    loyal: dict[uuid.UUID, list[int]] = defaultdict(list)
    for seller in clean_sellers + [r.seller_id for r in rings]:
        for _ in range(rng.randint(0, 2)):
            loyal[seller].append(rng.randrange(len(honest)))

    slots: list[tuple[uuid.UUID, Ring | None]] = []
    budget = config.n_auctions - config.min_clean_auctions
    for index, ring in enumerate(rings):
        rings_after = config.n_rings - index - 1  # each still needs at least one auction
        works = ring.pattern.auctions if budget - ring.pattern.auctions >= rings_after else 1
        slots.extend((ring.seller_id, ring) for _ in range(works))
        budget -= works
    while len(slots) < config.n_auctions:
        seller = (rng.choice(rings).seller_id if rng.random() < 0.2 else rng.choice(clean_sellers))
        slots.append((seller, None))
    rng.shuffle(slots)

    auctions: list[AuctionPlan] = []
    for seller_id, ring in slots:
        opens_at = config.start + timedelta(seconds=rng.uniform(0, (config.span_days - 3) * 86400))
        opens_at = opens_at.replace(microsecond=0)
        duration = timedelta(hours=rng.uniform(24, 72))
        starting = _money(round(10 * (80 ** rng.random())))  # log-uniform 10..800
        auctions.append(AuctionPlan(
            auction_id=new_id(), seller_id=seller_id, opens_at=opens_at,
            closes_at=(opens_at + duration).replace(microsecond=0), starting_price=starting,
            valuation=_money(float(starting) * rng.uniform(1.6, 4.0)), ring=ring,
        ))

    dataset = Dataset(config=config, auctions=auctions, rings=rings)
    for auction in auctions:
        _simulate(dataset, auction, rng, new_id, honest, loyal)
    dataset.events.sort(key=lambda e: (e["accepted_at"], e["auction_id"], e["server_seq"]))
    dataset.labels.sort(key=lambda lb: (str(lb.ring_id), str(lb.auction_id), str(lb.bidder_id)))
    return dataset


def _simulate(
    dataset: Dataset,
    auction: AuctionPlan,
    rng: random.Random,
    new_id: _Ids,
    honest: list[tuple[uuid.UUID, str]],
    loyal: dict[uuid.UUID, list[int]],
) -> None:
    span = (auction.closes_at - auction.opens_at).total_seconds()
    attempts: list[_Attempt] = []

    def add(offset_seconds: float, bidder: uuid.UUID, fingerprint: str | None,
            ceiling: Decimal, shill: bool) -> None:
        at = auction.opens_at + timedelta(seconds=min(max(offset_seconds, 1.0), span - 1.0))
        attempts.append(_Attempt(at, len(attempts), bidder, fingerprint, ceiling, shill))

    participants = rng.sample(range(len(honest)), rng.randint(3, 12))
    participants += [i for i in loyal.get(auction.seller_id, []) if rng.random() < 0.6]
    for index in dict.fromkeys(participants):
        account, fingerprint = honest[index]
        ceiling = _money(float(auction.valuation) * rng.lognormvariate(0, 0.25))
        for _ in range(rng.randint(1, 4)):
            device = None if rng.random() < 0.05 else fingerprint
            add(span * rng.betavariate(2.2, 0.9), account, device, ceiling, False)

    if auction.ring is None and rng.random() < dataset.config.bidding_war_rate:
        rivals = rng.sample(range(len(honest)), 2)
        offset = span * rng.uniform(0.95, 0.985)
        for turn in range(rng.randint(8, 20)):
            account, fingerprint = honest[rivals[turn % 2]]
            offset += rng.uniform(5, 30)
            add(offset, account, fingerprint, _money(float(auction.valuation) * 1.3), False)

    ring = auction.ring
    if ring is not None:
        pattern = ring.pattern
        target = auction.starting_price + _money(
            float(auction.valuation - auction.starting_price) * pattern.push_fraction)
        offset = span * rng.uniform(0.01, 0.04)
        stop = span * (1 - pattern.stop_before_close)
        mean_gap = 60.0 / pattern.bids_per_minute
        budget = rng.randint(pattern.size + 1, pattern.size * 3 + 2)  # shill bids it will try
        turn = 0
        while offset < stop and turn < budget:
            member = turn % len(ring.accounts)
            add(offset, ring.accounts[member], ring.fingerprints[member], target, True)
            offset += mean_gap * max(0.05, 1 + pattern.interarrival_cv * rng.gauss(0, 1))
            turn += 1

    leader: uuid.UUID | None = None
    price: Decimal | None = None
    seq = 0
    shills_seen: set[uuid.UUID] = set()
    for attempt in sorted(attempts, key=lambda a: (a.at, a.order)):
        if attempt.bidder_id == leader:
            continue
        minimum = auction.starting_price if price is None else price + increment_for(price)
        if minimum > attempt.ceiling:
            continue
        amount = minimum
        if not attempt.shill:
            extra = increment_for(minimum) * rng.choice((0, 0, 1, 2))
            amount = min(attempt.ceiling, minimum + extra)
        seq += 1
        price, leader = amount, attempt.bidder_id
        if attempt.shill:
            shills_seen.add(attempt.bidder_id)
        dataset.events.append({
            "event_id": str(new_id()),
            "schema_version": 1,
            "auction_id": str(auction.auction_id),
            "bid_id": str(new_id()),
            "bidder_id": str(attempt.bidder_id),
            "seller_id": str(auction.seller_id),
            "amount": str(amount),
            "currency": dataset.config.currency,
            "server_seq": seq,
            "accepted_at": _iso(attempt.at),
            "auction_closes_at": _iso(auction.closes_at),
            "idempotency_key": f"ds-{new_id()}",
            "device_fingerprint": attempt.fingerprint,
            "increment_stale": False,
        })
    if ring is not None:
        signals = "|".join(ring.pattern.signals)
        for account in ring.accounts:
            if account in shills_seen:
                dataset.labels.append(Label(ring.ring_id, ring.seller_id, auction.auction_id,
                                            account, signals))


def events_jsonl(dataset: Dataset) -> bytes:
    return b"".join(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for event in dataset.events
    )


def labels_csv(dataset: Dataset) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(LABEL_COLUMNS)
    for label in dataset.labels:
        writer.writerow([label.ring_id, label.seller_id, label.auction_id, label.bidder_id,
                         label.signals])
    return buffer.getvalue().encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(dataset: Dataset, directory: Path) -> dict[str, str]:
    """Write the gzipped events and the labels; return the SHA-256 of each uncompressed file.

    The gzip header carries no timestamp or name, but compressed bytes can still differ
    between zlib builds, so reproducibility is checked on the uncompressed content.
    """
    directory.mkdir(parents=True, exist_ok=True)
    events = events_jsonl(dataset)
    with (directory / EVENTS_FILE).open("wb") as raw, \
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as out:
        out.write(events)
    labels = labels_csv(dataset)
    (directory / LABELS_FILE).write_bytes(labels)
    return {EVENTS_FILE: digest(events), LABELS_FILE: digest(labels)}


def summary(dataset: Dataset) -> dict[str, int]:
    shilled = {a.auction_id for a in dataset.auctions if a.ring is not None}
    shill_pairs = {(str(lb.auction_id), str(lb.bidder_id)) for lb in dataset.labels}
    return {
        "auctions": len(dataset.auctions),
        "rings": len({lb.ring_id for lb in dataset.labels}),
        "shilled_auctions": len(shilled),
        "clean_auctions": len(dataset.auctions) - len(shilled),
        "events": len(dataset.events),
        "shill_events": sum(
            1 for e in dataset.events if (e["auction_id"], e["bidder_id"]) in shill_pairs
        ),
        "labelled_accounts": len({lb.bidder_id for lb in dataset.labels}),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DatasetConfig.seed)
    args = parser.parse_args(argv)
    dataset = generate(DatasetConfig(seed=args.seed))
    digests = write(dataset, args.out)
    print(json.dumps({"summary": summary(dataset), "sha256": digests}, indent=2))


if __name__ == "__main__":
    main()
