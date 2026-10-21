# Shill detector v1: first measurement (#53, #54, milestone #107)

**Detector** `shill-v1` · **Dataset** v1 (`tests/fixtures/fraud/`, 500 auctions, 200 labelled rings, seed 20260904)
· **Measured** 2026-10-19 with `services/fraud-detector/eval/quick_eval.py` · **Target** (NFR-FRAUD-1):
recall ≥ 0.90 at precision ≥ 0.75.

This is the early, honest number Plan 5 asks for. The formal harness with the published curve is #57 (Plan 7).

## Result

| Dataset | Recall | Precision | Auction recall | Auction precision | Late alerts | Median lead before close |
|---|---|---|---|---|---|---|
| **v1 (fixture)** | **0.9025** | **0.9325** | 1.0000 | 0.8729 | 0 | 42.0 h |
| held-out, seed 1 | 0.9014 | 0.9193 | 1.0000 | 0.8576 | 0 | — |
| held-out, seed 7 | 0.9146 | 0.9177 | 1.0000 | 0.8344 | 0 | 41.7 h |

The target is met, just barely on recall. Recall by labelled ring signal (v1): shared fingerprint 0.967,
seller-linked 0.910, high velocity 0.899, regular inter-arrival 0.890.

**How it is counted.** The unit is a labelled (auction, shill account) pair (903 in v1). A pair is detected when a
`ShillAlert` raised **before that auction's close** names the account in `suspect_bidder_ids`. Precision is over
every pair named that way. An alert at or after close is never published and counts as a miss
(`AlertPublisher` → `must_precede_close`). The replay runs through the real path:
`FraudConsumer.handle` → `FeatureExtractor` → `ShillDetector` → `AlertPublisher`, in replay time.

## Recall–precision curve (v1, threshold sweep)

| Threshold | 0.40–0.50 | 0.55 | **0.60** | 0.65 | 0.70 | 0.75 | 0.80 |
|---|---|---|---|---|---|---|---|
| Recall | 1.000 | 0.903 | **0.903** | 0.888 | 0.865 | 0.769 | 0.398 |
| Precision | 0.37–0.38 | 0.906 | **0.933** | 0.950 | 0.965 | 0.967 | 1.000 |

Reproduce: `cd services/fraud-detector && python -m eval.quick_eval --sweep`.

## The v1 scorer

Score = weighted mean of signal strengths on 0..1; a bidder at ≥ 0.60 is a suspect, and the auction gets an alert
each time a new suspect appears.

| SDD signal | Computed as | Weight |
|---|---|---|
| `selfBidRatio` | share of the bidder's bids that were on this seller | 2 |
| `bidVelocity` | bids/minute in this auction, logistic around 0.05/min | 1 |
| `fingerprintOverlap` | other accounts on this bidder's device **in this auction** (#54) | 1 |
| `interArrivalStdDev` | gap regularity (1 − CV) | 0 |
| `accountAgeDays` | days since first seen on `bid.events` (proxy) | 0 |
| `winRateWithSeller` | share of this seller's closed auctions the bidder won | 0 |
| `graphDegreeToSeller` | distinct sellers bid with | 0 |

All seven are reported in the alert's `signals`. Seller links alone score 0.5, so they never trigger an alert:
loyal buyers and brand-new honest accounts look seller-linked too. An alert needs velocity or a shared device
as well.

**What the measurement changed.** Counting fingerprint sharing *anywhere* (households) gave precision 0.845 at
the same recall. Counting it *within the auction* gave 0.933. The weights came from a small grid search on v1
and were then checked on the two held-out seeds above, which were never used for tuning. The four zero-weight
signals didn't improve either number on this dataset. Per-bidder regularity is noisy because ring members take
turns, and the other three need history the 28-day dataset barely has.

## Known limits (input to Plan 6 tuning)

- **The recall ceiling is about 0.90.** The missed pairs are mostly ring accounts with a single bid in the auction
  and no shared device: nothing in one bid separates them from an honest newcomer. Ring clustering (#55) should
  catch them through their ring-mates.
- **Velocity is calibrated to the dataset.** Honest bids there are hours apart. In a short live demo, honest
  newcomers who bid every minute on one seller score 0.75 and get flagged. `accountAgeDays` from auth's real
  sign-up date (not the stream proxy) is the planned fix. Until then, raise `FRAUD_ALERT_THRESHOLD` for demos
  with fast honest bidding.
- **After a restart, windows start empty.** An auction already in flight is scored only on the bids after the
  restart. Offsets are committed, so nothing is re-read or lost, and bidding is unaffected.
- The dataset generator wrote both the rings and the honest look-alikes, so these numbers measure the detector
  against our own model of shilling, not against real fraud.
