# ADR-0012: Monorepo, service template, schema-per-service

| | |
|---|---|
| **Status** | **Proposed**: the team decides at the Plan 1 review (Aug 14) |
| **Date** | 2026-08-14 |
| **Owner** | Ayush |
| **Requirements** | NFR-SCALE-1, NFR-MAINT-2..4, FR-INFRA-1..3; SDD 2.3, 3.3, 4.1 |

## Decision

1. **One monorepo** holds all services, contracts, infrastructure and docs. With 8 people and 13 services, atomic
   cross-service changes to contracts, plus one CI configuration, outweigh the isolation that separate repos would give.
2. **Each service is independently deployable**: its own Dockerfile (`services/<name>/Dockerfile`, built from
   the repository root) and its own Render service. One service can be rebuilt and restarted without touching the others.
3. **One shared template library**, `libs/zeo-common`, installed into every image. It provides health, readiness, metrics,
   request ids, the error envelope, logging and money handling. Services must not re-implement these.
4. **One PostgreSQL instance, one schema and role per service**, enforced by GRANTs (SDD 4.1). Splitting into
   separate instances later is a connection-string change only.
5. **Single-broker Kafka** (KRaft) locally and on Render through week 13. Broker count is revisited only if week-14 load
   testing shows Kafka is the bottleneck. If the Render private service proves unreliable, the fallback is an external
   managed cluster (for example a hosted Kafka free tier), and only `KAFKA_BOOTSTRAP_SERVERS` changes.
6. **Python 3.11 + FastAPI** in every image. Developers may run newer Python locally, but CI and images use 3.11.

## Consequences

- `docker compose up` is the single way to run the system, and CI uses the same file (environment parity).
- Contract changes and their implementation can land in one PR.
- The image build context is the repository root, so each Dockerfile copies only `libs/zeo-common` and its own service folder.
