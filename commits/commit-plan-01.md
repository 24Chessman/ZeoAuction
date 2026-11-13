# Commit plan — Plan 1: Setup & Foundations (weeks 1–2, Aug 3 – Aug 14)

**Status: implemented.** Every file below exists in the working tree.
[`plan-01-commits.sh`](plan-01-commits.sh) holds exactly this list:
- `--check` verifies that every file in the repository is in exactly one commit.
- `--apply` creates all 33 commits, each authored by its member.

The replay was tested: all test suites pass at the end of the history, and the contract tests pass at every checkpoint along it.

**Milestone:** #103 *Setup phase integrated*. After commit 33, Ayush tags `plan-01`.

## Summary by member

| Member | Commits | What they own in Plan 1 |
|---|---|---|
| Ayush | 9 | Repo bootstrap, the `zeo-common` template, roles/schemas + auth/notify DB, seed + guard proofs, auth-user and ws-gateway skeletons, the Compose stack (#88), Kafka on Render (#89), CI, ADR-0012 |
| Sumit | 8 | Project docs import, contract base, **state machines (#28)**, architecture/conventions/ADR index, topic topology + CT-1, auction schema, orchestrator and flusher skeletons, topic sync test |
| Jaydip | 4 | SettlementStep v1, ADR-0009 + ADR-0011 + settlement policy, **payment schema with the append-only ledger**, payment-escrow skeleton |
| Naitik | 3 | **Bid service contract + rejection taxonomy (#18)**, bids table, bid and escrow-sweep skeletons |
| Harshal | 3 | **BidAccepted v1 + ShillAlert v1 (#50)**, fraud tables, fraud-detector skeleton |
| Sagar | 3 | CT-3 pricing contract, kyc/pricing/search schemas, kyc/pricing/search skeletons |
| Jay | 2 | Dispute and admin schemas (append-only audit log), dispute and admin-moderation skeletons |
| Gaurang | 1 | ADR-0010 (notifications and image hosting) |

Jira gives Sagar, Jaydip, Gaurang and Jay no sprint-1 tickets, so their Plan 1 commits are the unticketed
milestone items: their service schemas, skeletons and ADRs. **Gaurang's optional pull-forward**, the React +
Vite + Tailwind scaffold, isn't in the repository yet. If Gaurang does it, it's one more commit:
`feat(frontend): scaffold React 18 + Vite + Tailwind app shell` → `frontend/`.

## Commits in merge order

### Wave 0 — foundation (before branch protection is switched on)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 1 | Ayush | `main` (initial) | `chore(repo): bootstrap repository config and tooling` | `.gitignore`, `.gitattributes`, `.editorconfig`, `pyproject.toml`, `requirements-dev.txt`, `.env.example` | #103 |
| 2 | Sumit | `main` | `docs(project): add proposal, system design, timeline and implementation plans` | `project_docs/`, `planing/`, `commits/` | #103 |
| 3 | Ayush | `ayush/88-service-template` | `feat(common): add zeo-common service template with health, metrics and error envelope` | `libs/zeo-common/`, `contracts/errors/common-error-codes.yaml` | #88 |

After commit 3: **turn on branch protection** (2 approvals, CI required).

### Wave 1 — contracts and design documents (parallel PRs, merged in this order)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 4 | Sumit | `sumit/28-contract-base` | `docs(contracts): add shared API components and contract rules` | `contracts/README.md`, `contracts/openapi/common.v1.yaml`, `tests/contracts/__init__.py`, `tests/contracts/conftest.py` | #28 |
| 5 | Sumit | `sumit/28-state-machines` | `docs(orchestration): specify auction, order, KYC and dispute state machines` | `docs/state-machines.md` | #28 |
| 6 | Sumit | `sumit/103-architecture-docs` | `docs: add architecture overview, engineering conventions and ADR index` | `docs/architecture.md`, `docs/engineering-conventions.md`, `docs/adr/README.md`, `docs/adr/0000-template.md` | #103 |
| 7 | Sumit | `sumit/28-topics-ct1` | `feat(contracts): define Kafka topic topology, AuctionStateChanged v1 and CT-1` | `contracts/events/topics.yaml`, `contracts/events/auction_state_changed.v1.json`, `contracts/events/examples/auction_state_changed.v1.json`, `contracts/openapi/internal/auction-state.v1.yaml` | #28 |
| 8 | Harshal | `harshal/50-bid-event-schema` | `feat(contracts): freeze BidAccepted v1 and ShillAlert v1 event schemas` | `contracts/events/bid_accepted.v1.json`, `contracts/events/shill_alert.v1.json`, their two `examples/`, `tests/contracts/test_event_schemas.py` | #50 |
| 9 | Jaydip | `jaydip/103-settlement-event` | `feat(contracts): add SettlementStep v1 event schema` | `contracts/events/settlement_step.v1.json`, `contracts/events/examples/settlement_step.v1.json` | #103 |
| 10 | Sagar | `sagar/103-ct3-pricing` | `feat(contracts): publish CT-3 minimum-increment contract` | `contracts/openapi/internal/pricing.v1.yaml` | #103 |
| 11 | Naitik | `naitik/18-bid-contract` | `feat(contracts): publish bid service contract and rejection taxonomy` | `contracts/openapi/bid-service.v1.yaml`, `contracts/errors/bid-rejection-codes.yaml`, `tests/contracts/test_openapi_contracts.py` | #18 |
| 12 | Jaydip | `jaydip/103-settlement-policy` | `docs(adr): propose payment provider and settlement policy, ADR-0009 and ADR-0011` | `docs/adr/0009-payment-provider.md`, `docs/adr/0011-settlement-policy.md`, `config/settlement-policy.yaml` | #103 |
| 13 | Gaurang | `gaurang/103-adr-third-party` | `docs(adr): propose notification and image-hosting approach, ADR-0010` | `docs/adr/0010-third-party-services.md` | #103 |
| 14 | Ayush | `ayush/103-adr-conventions` | `docs(adr): propose repository and platform conventions, ADR-0012` | `docs/adr/0012-repository-and-platform-conventions.md` | #103 |

Commit 11 must merge after 7 and 10, because its test reads the CT-1 and CT-3 contracts.

### Wave 2 — database schemas (commit 15 first, then the rest in any order, with 22 last)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 15 | Ayush | `ayush/103-db-roles` | `feat(db): create per-service roles and schemas, auth and notify tables` | `infra/postgres/init/00-roles-and-schemas.sql`, `10-auth.sql`, `90-notify.sql` | #103 |
| 16 | Sagar | `sagar/103-db-schemas` | `feat(db): add kyc, pricing and search schemas` | `infra/postgres/init/20-kyc.sql`, `50-pricing.sql`, `80-search.sql` | #103 |
| 17 | Sumit | `sumit/28-db-auction` | `feat(db): add auction schema with lifecycle audit table` | `infra/postgres/init/30-auction.sql` | #28 |
| 18 | Naitik | `naitik/18-db-bids` | `feat(db): add bids table with server_seq and idempotency constraints` | `infra/postgres/init/40-bid.sql` | #18 |
| 19 | Jaydip | `jaydip/103-db-payment` | `feat(db): add payment schema with append-only escrow ledger and fee config` | `infra/postgres/init/60-payment.sql`, `tests/contracts/test_settlement_policy.py` | #103 |
| 20 | Harshal | `harshal/50-db-fraud` | `feat(db): add fraud alert and evaluation tables` | `infra/postgres/init/75-fraud.sql` | #50 |
| 21 | Jay | `jay/103-db-dispute-admin` | `feat(db): add dispute and admin schemas with append-only audit log` | `infra/postgres/init/70-dispute.sql`, `85-admin.sql` | #103 |
| 22 | Ayush | `ayush/103-db-verify` | `test(db): add dev seed data and schema guard verification` | `infra/postgres/seed/`, `infra/postgres/verify-guards.sql` | #103 |

**Schema reviewers:** Jaydip reviews 19 together with Sumit (the ledger invariants). Every schema PR also needs Ayush's approval (grants).

### Wave 3 — service skeletons (each owner scaffolds their own service from the template)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 23 | Ayush | `ayush/88-scaffold` | `feat(services): scaffold auth-user and ws-gateway from the template` | `services/auth-user/`, `services/ws-gateway/` | #88 |
| 24 | Naitik | `naitik/88-scaffold` | `feat(services): scaffold bid and escrow-sweep from the template` | `services/bid/`, `services/escrow-sweep/` | #88 |
| 25 | Sumit | `sumit/88-scaffold` | `feat(services): scaffold auction-orchestrator and bid-flusher from the template` | `services/auction-orchestrator/`, `services/bid-flusher/` | #88 |
| 26 | Sagar | `sagar/88-scaffold` | `feat(services): scaffold kyc, pricing and search-analytics from the template` | `services/kyc/`, `services/pricing/`, `services/search-analytics/` | #88 |
| 27 | Jaydip | `jaydip/88-scaffold` | `feat(services): scaffold payment-escrow from the template` | `services/payment-escrow/` | #88 |
| 28 | Jay | `jay/88-scaffold` | `feat(services): scaffold dispute and admin-moderation from the template` | `services/dispute/`, `services/admin-moderation/` | #88 |
| 29 | Harshal | `harshal/88-scaffold` | `feat(services): scaffold fraud-detector from the template` | `services/fraud-detector/` | #88 |

### Wave 4 — integration and the gate (Ayush, after every skeleton is merged)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 30 | Ayush | `ayush/88-compose-stack` | `build(infra): single Docker Compose stack with Kafka, PostgreSQL, Redis and S3 storage` | `docker-compose.yml`, `infra/kafka/create-topics.sh`, `infra/s3/`, `Makefile`, `scripts/test-all.sh`, `README.md` | #88 |
| 31 | Sumit | `sumit/28-topic-sync-test` | `test(contracts): keep the topic contract and the topic script in sync` | `tests/contracts/test_topics.py` | #28 |
| 32 | Ayush | `ayush/89-kafka-render` | `build(kafka): run Kafka as a Render private service with a persistent disk` | `infra/kafka/Dockerfile`, `infra/kafka/entrypoint-render.sh`, `infra/kafka/smoke-test.sh`, `render.yaml` | #89 |
| 33 | Ayush | `ayush/103-ci` | `ci: run lint, unit and contract tests on every pull request` | `.github/` | #103 |

CI is last because its matrix builds all 13 services, and they must all exist first.

## Milestone gate #103 (Ayush runs it, and the team reviews the result)

These were verified during implementation:
- [x] `docker compose up` brings all 17 long-running containers up (16 report healthy; the escrow-sweep loop has no health check), and both init jobs exit 0
- [x] Kafka topics match `contracts/events/topics.yaml` (12/6/6/3 partitions, retention, compaction)
- [x] `make verify-db` passes all 8 guard proofs: schema isolation, append-only ledger, single terminal row, idempotency key, ledger sums to zero, unique `server_seq`, KYC column-only grant, append-only audit log
- [x] The Kafka smoke test shows a message surviving a broker restart. The Render image boots, creates the topics, and refuses to start without `KAFKA_ADVERTISED_HOST`
- [x] KYC and dispute buckets are private (403 anonymous) and encrypted at rest (SSE-S3). Signed URLs work
- [x] `ruff check .` is clean, and 111 tests pass (31 library + 31 contract + 49 service)

These still need the team:
- [ ] State machines signed off (sign-off table in `docs/state-machines.md`)
- [ ] ADR-0009, 0010, 0011 and 0012 accepted (they're still **Proposed**)
- [ ] Render: deploy the blueprint, set `KAFKA_ADVERTISED_HOST`, run the smoke test on the hosted disk
- [ ] Branch protection on, and CODEOWNERS handles filled in
- [ ] Tag `plan-01`
