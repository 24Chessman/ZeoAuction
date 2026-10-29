# Shill detector v2: measurement after bid-ring clustering (#55, #56, milestone #108)

**Detector** `shill-v2` (with bid-ring clustering) · **Dataset** v1 (`tests/fixtures/fraud/`, 500 auctions, 200 labelled rings, seed 20260904)
· **Measured** 2026-10-28 with `services/fraud-detector/eval/quick_eval.py` · **Target** (NFR-FRAUD-1):
recall ≥ 0.90 at precision ≥ 0.75.

Plan 6 added cross-auction bid-ring clustering (`app/clustering.py`) from shared device fingerprints and
the bipartite bidder-seller graph. This document records the re-measured recall and precision.

## Result

| Dataset | Recall | Precision | Auction recall | Auction precision | Late alerts | Median lead before close |
|---|---|---|---|---|---|---|
| **v2 (fixture)** | **0.9418** | **0.9512** | 1.0000 | 0.9120 | 0 | 42.5 h |
| held-out, seed 1 | 0.9385 | 0.9450 | 1.0000 | 0.8990 | 0 | 42.1 h |
| held-out, seed 7 | 0.9430 | 0.9428 | 1.0000 | 0.8875 | 0 | 42.0 h |

### Impact of Clustering
- **Recall improved from 0.9025 to 0.9418 (+3.93%)**: Bidders operating in coordinated rings across multiple auctions that previously stayed just under the single-auction anomaly threshold are now detected via ring membership.
- **Precision improved from 0.9325 to 0.9512 (+1.87%)**: False positives from coincidental single-auction overlap are filtered out when no multi-auction cluster can be formed.
- **Ring ID linkage**: Alerts now include a stable `ring_id` correlating colluding accounts across the platform.

## Recall–precision curve (v2, threshold sweep)

| Threshold | 0.40–0.50 | 0.55 | **0.60** | 0.65 | 0.70 | 0.75 | 0.80 |
|---|---|---|---|---|---|---|---|
| Recall | 1.000 | 0.945 | **0.942** | 0.925 | 0.901 | 0.824 | 0.450 |
| Precision | 0.42–0.45 | 0.925 | **0.951** | 0.968 | 0.978 | 0.985 | 1.000 |

## Integration with Dispute Management (#56)
Detected rings with high confidence trigger automatic dispute creation via `services/dispute/app/adapters/fraud_consumer.py`, attaching the cluster's bid trace as evidence and blocking order settlement pending adjudication.
