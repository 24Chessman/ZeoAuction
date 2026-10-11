# escrow-sweep

| | |
|---|---|
| **Component** | Escrow sweep (cron) |
| **Interface owner** | Naitik |
| **Kind** | Cron job |
| **Owns schema** | none; reads `payment.orders` through the `sweep_svc` role and releases through the Payment API |
| **Design** | SDD 3.4, 6.6; ADR-0006 |
| **Next work** | #25 (Plan 6), #97 Render cron (Plan 6) |

## Responsibility

Runs every minute: finds SHIPPED orders whose protection window has expired and asks Payment to release them with an idempotency key. Must release within 5 minutes (AC-12).

## Run

```bash
docker compose up -d escrow-sweep          # Compose runs it every 60 s, mirroring the Render cron
cd services/escrow-sweep && pytest         # unit tests (after installing libs/zeo-common)
```

A cron job has no HTTP surface, so it uses only the JSON logging from `libs/zeo-common`. Success or failure is reported by the process exit code, and `escrow_sweep_lag_seconds` is added in Plan 6.
