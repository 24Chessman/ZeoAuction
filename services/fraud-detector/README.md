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
| **Next work** | #52 (Plan 4) |

## Responsibility

Streaming consumer on `bid.events`: per-auction sliding windows, shill scoring, ring clustering, alerts to `fraud.alerts` before auction close.

## Run

```bash
docker compose up -d fraud-detector          # as part of the stack
cd services/fraud-detector && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
