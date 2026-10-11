# pricing

| | |
|---|---|
| **Component** | Pricing Engine |
| **Interface owner** | Sagar |
| **Kind** | HTTP API service |
| **Owns schema** | `pricing` (database role `pricing_svc`) |
| **Design** | SDD 2.4, 7.2 (Pricing); contracts/openapi/internal/pricing.v1.yaml |
| **Next work** | #42-#44 (Plan 4) |

## Responsibility

Bid-velocity tracking, dynamic minimum increment (contract CT-3), hot-auction flagging.

## Run

```bash
docker compose up -d pricing          # as part of the stack
cd services/pricing && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
