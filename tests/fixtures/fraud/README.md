# Fraud dataset v1 — 500 auctions, 200 labelled shill rings

| | |
|---|---|
| **Jira** | #51 (owner: Harshal) · ADR-0008: the dataset exists before any detector |
| **Generator** | `services/fraud-detector/dataset/generator.py` (seed `20260904`) |
| **Replay** | `services/fraud-detector/dataset/replay.py` publishes it to `bid.events` |

## Files

| File | Content |
|---|---|
| `dataset-v1.jsonl.gz` | 10,817 `BidAccepted v1` events, one JSON object per line, in time order. Each line validates against `contracts/events/bid_accepted.v1.json`, so the file can be replayed into Kafka exactly like live traffic. |
| `labels-v1.csv` | One row per shill account per auction it bid in: `ring_id, seller_id, auction_id, bidder_id, signals`. Every account **not** listed is honest. `signals` lists the ring's planted behaviours, separated by `\|`. |

| Count | Value |
|---|---|
| Auctions | 500 (261 worked by a ring, 239 clean) |
| Rings | 200 (2–5 accounts each; 694 labelled accounts) |
| Shill bids | 2,166 of 10,817 (20%) |

## What a ring looks like

Each ring belongs to one seller and works one or two of that seller's auctions. It bids early and
in minimum increments, pushes the price towards what honest bidders will pay, and stops before the
close so that it rarely wins. Its behaviour is drawn from four independent signals, so the Section 10
recall and precision can be broken down per signal:

| Signal | Planted as |
|---|---|
| `seller_linked` | The ring's accounts bid on no other seller's auctions |
| `shared_fingerprint` | The ring uses fewer device fingerprints than it has accounts |
| `high_velocity` | Shill bursts at 2–6 bids per minute |
| `regular_interarrival` | Gaps between shill bids have a coefficient of variation ≤ 0.25 |

Clean auctions contain **look-alikes**: households where two honest accounts share a device, loyal
buyers who keep returning to one seller, and fast end-of-auction bidding wars. A detector that flags
any single signal on its own will pay for it in precision.

Every auction obeys the live bidding rules: `server_seq` runs 1..n, each bid beats the previous one
by at least the CT-3 tier increment, nobody outbids themselves, sellers never bid, and every bid is
accepted before the close.

## Reproducing it

```bash
cd services/fraud-detector
python -m dataset.generator --out ../../tests/fixtures/fraud
```

The output is byte-identical for the same seed, and was checked on Python 3.11 and 3.14. Compressed
bytes can differ between zlib builds, so reproducibility is checked on the **uncompressed** content.
`services/fraud-detector/tests/test_dataset_fixture.py` regenerates the dataset and compares:

| File (uncompressed) | SHA-256 |
|---|---|
| `dataset-v1.jsonl` | `a0d3149c9f121db51265fb59fc5c0bfa828fcc7e8fd894680901ba4eb0579c57` |
| `labels-v1.csv` | `c6e864e267f9e6cc0a97b23bd3476bec3d718799d4ec4ebff5efc48cecc12e0a` |

Changing the generator changes these digests. That is a new dataset version (`v2`), not an edit
to `v1`, because evaluation runs (`fraud.evaluation_runs.dataset_version`) refer to it by name.

## Replaying into Kafka

```bash
cd services/fraud-detector
python -m dataset.replay --bootstrap localhost:29092 \
    --file ../../tests/fixtures/fraud/dataset-v1.jsonl.gz --shift-to-now
```

`--shift-to-now` moves every timestamp by the same offset, so the latest close is an hour away and
"alert before close" (AC-14) still means something. `--rate N` limits publishing to N events per second.
