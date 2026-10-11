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
| **Next work** | #54–#57 scorer, ring clustering, alerts (Plan 5) |

## Responsibility

Streaming consumer on `bid.events`: per-auction sliding windows, shill scoring, ring clustering, alerts to `fraud.alerts` before auction close.

## Streaming scaffold (#52)

- `FraudConsumer` reads `bid.events` as group `fraud-detector` (`auto_offset_reset=earliest`, auto-commit off) and
  commits after each event is folded in, so a restart resumes from the committed offset (at-least-once).
- `AuctionWindows` keeps the last `FRAUD_WINDOW_EVENTS` (200) bids per auction in `server_seq` order. A redelivered
  `server_seq` is dropped; gaps are normal (a bid that loses the compare-and-set burns its number) and only counted.
  A window is dropped `FRAUD_CLOSE_GRACE_MINUTES` (10) after its auction's latest `auction_closes_at`.
- Each accepted event goes through `FeatureExtractor` (#53) and then to the `on_features` hook, where the Plan 5
  scorer plugs in. A failing hook is logged and never stops consumption.
- It's a separate worker that only reads `bid.events`, so stopping it can't affect bidding.
- After a restart the windows start empty. Rebuilding them for still-open auctions belongs to the Plan 5 scorer (#55).
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

## Run

```bash
docker compose up -d fraud-detector          # as part of the stack
cd services/fraud-detector && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
