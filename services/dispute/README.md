# dispute

| | |
|---|---|
| **Component** | Dispute Management |
| **Interface owner** | Jay |
| **Kind** | HTTP API service |
| **Owns schema** | `dispute` (database role `dispute_svc`) |
| **Design** | SDD 5.2.4, 6.6, 7.5, 7.6, 8.6, 8.7 |
| **Next work** | #84 (Plan 6) |

## Responsibility

Window-gated disputes, evidence, freeze, and administrator adjudication. Issues freeze/release/refund commands to Payment; never writes the ledger.

## Run

```bash
docker compose up -d dispute          # as part of the stack
cd services/dispute && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
