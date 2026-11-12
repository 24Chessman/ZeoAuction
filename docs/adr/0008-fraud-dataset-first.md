# ADR-0008: Fraud dataset built before the detector

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.8, ratified in Plan 7, #58) |
| **Date** | 2026-11-02 |
| **Owner** | Harshal |
| **Deciders** | Harshal, Sumit, Ayush |
| **Requirements** | FR-FRAUD-1, AC-14; SDD §2.6.8; tests/fixtures/fraud/README.md |

## Context

Shill bidding (collusion between seller and fake bidders to artificially inflate prices)
and Sybil rings represent existential risks to auction integrity.
Developing detection algorithms without an authoritative, labeled behavioral dataset leads
to subjective threshold tuning, undetected regressions, and unverified production accuracy.
Success metric AC-14 explicitly demands: **recall >= 0.90 at precision >= 0.75**, with alerts
emitted strictly **before** the auction closes (late alerts count as misses).

## Options considered

1. **Ad-hoc heuristic rules written on live streams**: impossible to benchmark or compare; no repeatable baseline.
2. **Train model on production logs after launch**: delays fraud protection until after users have been defrauded.
3. **Dataset-first methodology with synthetic multi-pattern generator**: generate a rich, reproducible, labeled benchmark dataset (`dataset-v1.jsonl.gz`, `labels-v1.csv`) simulating honest bidding alongside known shill patterns; build the evaluation harness before implementing the real-time detector.

## Decision

**Option 3: Dataset-first development.**
1. Synthetic dataset `fixtures/fraud/dataset-v1.jsonl.gz` contains over 10,000 bids across 100 auctions with ground-truth labels `labels-v1.csv`.
2. Patterns modeled:
   - Normal incremental bidding
   - Seller-bidder IP / device fingerprint clustering
   - Rapid price elevation followed by bidder drop-out
   - Cyclic bidding rings
3. Timing invariant: Alerts must be emitted while the auction is OPEN. Any alert generated after `auction_closes_at` is scored as a **miss** (false negative) regardless of model confidence.
4. Evaluation harness computes precision, recall, and F1 score against the benchmark dataset in CI.

## Consequences

- **Verifiable SLA**: Algorithm tuning is objectively measured against AC-14 (recall >= 0.90, precision >= 0.75).
- **Regression prevention**: Any changes to feature extraction or clustering algorithms run against the fixed benchmark.
- **Explainability**: Alerts link to specific risk factors (`seller_linked`, `device_cluster`, `bid_velocity`).

## Evidence

- Fixtures committed in `tests/fixtures/fraud/`.
- Unit and evaluation suites in `services/fraud-detector/tests/` verify precision and recall targets exceed AC-14 thresholds.
