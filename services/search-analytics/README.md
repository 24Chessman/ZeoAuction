# search-analytics

| | |
|---|---|
| **Component** | Search & Analytics |
| **Interface owner** | Sagar |
| **Kind** | HTTP API service |
| **Owns schema** | `search` (database role `search_svc`) |
| **Design** | SDD 4.2.2, 7.7, 8.2, 8.5 |
| **Next work** | #46, #47 (Plan 6) |

## Responsibility

Full-text search over an auction projection (GIN index) and the seller dashboard.

## Run

```bash
docker compose up -d search-analytics          # as part of the stack
cd services/search-analytics && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
