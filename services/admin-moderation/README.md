# admin-moderation

| | |
|---|---|
| **Component** | Admin & Moderation |
| **Interface owner** | Jay |
| **Kind** | HTTP API service |
| **Owns schema** | `admin` (database role `admin_svc`) |
| **Design** | SDD 8.8, 9.1; FR-ADMIN-* |
| **Next work** | #81-#83 (Plan 6) |

## Responsibility

Listing review queue, user suspension, the append-only audit log, daily metrics, broadcasts.

## Run

```bash
docker compose up -d admin-moderation          # as part of the stack
cd services/admin-moderation && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
