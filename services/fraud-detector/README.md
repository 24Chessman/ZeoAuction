# fraud-detector

| | |
|---|---|
| **Component** | Fraud Detection (worker) |
| **Interface owner** | Harshal |
| **Kind** | Background worker |
| **Owns schema** | `fraud` (database role `fraud_svc`) |
| **Design** | SDD 5.4; contracts/events/bid_accepted.v1.json |
| **Plan 2** | #51 labelled dataset: `dataset/` and `tests/fixtures/fraud/` |
| **Plan 3** | #53 pulled forward: `app/features.py`, sliding-window shill features (seller link, shared fingerprint, velocity, inter-arrival regularity) |
| **Plan 4** | #52 streaming scaffold: `app/consumer.py` (group `fraud-detector`, manual commits), `app/windows.py` (per-auction sliding windows) |
| **Plan 5** | #53 shill scorer (`app/scorer.py`, `app/signals/`), #54 fingerprint signals (`app/signals/fingerprint.py`), `ShillAlert v1` publisher (`app/alerts.py`), v1 measurement (`eval/quick_eval.py`, `docs/fraud/v1-measurement.md`) |
| **Next work** | #55 ring clustering, #56 fraud-triggered disputes, #57 evaluation harness (Plans 6–7) |

## Responsibility

Streaming consumer on `bid.events`: per-auction sliding windows, shill scoring, ring clustering, alerts to `fraud.alerts` before auction close.

## Streaming scaffold (#52)

- `FraudConsumer` reads `bid.events` as group `fraud-detector` (`auto_offset_reset=earliest`, auto-commit off) and
  commits after each event is folded in, so a restart resumes from the committed offset (at-least-once).
- `AuctionWindows` keeps the last `FRAUD_WINDOW_EVENTS` (200) bids per auction in `server_seq` order. A redelivered
  `server_seq` is dropped; gaps are normal (a bid that loses the compare-and-set burns its number) and only counted.
  A window is dropped `FRAUD_CLOSE_GRACE_MINUTES` (10) after its auction's latest `auction_closes_at`.
- Each accepted event goes through `FeatureExtractor` (#53) and then to the `on_features` hook, where the shill
  scorer plugs in. A failing hook is logged and never stops consumption.
- It's a separate worker that only reads `bid.events`, so stopping it can't affect bidding.
- After a restart the windows start empty, and in-flight auctions are scored on the bids after it. Rebuilding from the
  7-day topic comes with ring clustering (#55).
- Metrics: `fraud_bid_events_total{outcome}` (accepted / duplicate / skipped), `fraud_open_windows`.

`tests/test_replay_resume.py` publishes the dataset with `dataset/replay.py` into a 12-partition fake of the topic
with group offsets. It proves in-order consumption, resume after a stop, and a single redelivery after a crash
between handling and commit. To check against the real broker:

```bash
docker compose up -d --build fraud-detector
cd services/fraud-detector && ../../.venv/Scripts/python.exe -m dataset.replay     --file ../../tests/fixtures/fraud/dataset-v1.jsonl.gz --shift-to-now
curl -s localhost:8011/metrics | grep fraud_bid_events_total   # accepted == events published
docker compose restart fraud-detector                          # nothing is re-read after a restart
```

## Shill detection v1 (#53, #54)

- Every accepted bid is scored in flight (`app/pipeline.py`): `FeatureExtractor` computes the seven SDD Table 5.3
  signals, and `ShillScorer` combines them (v1 weights: `selfBidRatio` 2, `bidVelocity` 1, `fingerprintOverlap` 1,
  the others reported but weighted 0). A bidder scoring at or above `FRAUD_ALERT_THRESHOLD` (0.60) is a suspect.
- Each new suspect in an auction produces a `ShillAlert v1` on `fraud.alerts` (key `auction_id`), listing every
  suspect so far. `must_precede_close` refuses an alert at or after the close: a late alert is stored in
  `fraud.fraud_alerts` as a miss and never published. `alert_id` is derived from (auction, bidder), so re-scoring
  after a restart stores and sends the same id again.
- `FRAUD_ALERT_PUBLISHER=kafka|memory`, `FRAUD_ALERT_REPOSITORY=postgres|memory` (Compose uses kafka + postgres).
- Metrics: `fraud_alerts_total{outcome}` (published / late / no_close).
- Measurement: `python -m eval.quick_eval` (v1: recall 0.9025, precision 0.9325, no late alerts);
  `--seed N` for a held-out dataset, `--sweep` for the curve, `--record $DATABASE_URL` to write
  `fraud.evaluation_runs`. Details and known limits: `docs/fraud/v1-measurement.md`.

## Run

```bash
docker compose up -d fraud-detector          # as part of the stack
cd services/fraud-detector && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
