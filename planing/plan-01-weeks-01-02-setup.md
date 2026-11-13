# Plan 1 — Setup & Foundations

| | |
|---|---|
| **Weeks** | 1–2 |
| **Dates** | Mon Aug 3 – Fri Aug 14, 2026 |
| **Jira sprint** | sprint-1 |
| **Milestone** | #103 *Setup phase integrated* (owner: Ayush) |
| **Proposal phase** | Setup — repository, Compose environment, architecture document, DB schema, bid-event schema, settlement policy fixed, CI skeleton |

## Goal

By Aug 14, every member can clone one repo, run `docker compose up`, and get a working empty skeleton of
the platform: Kafka, PostgreSQL, Redis and S3-compatible storage running, plus a hello-world FastAPI container for each
service with health endpoints. On top of that skeleton, the **contracts that everyone codes against** are
written down and frozen: the auction state machine, the bid service contract, the `BidAccepted` event
schema, the settlement policy numbers, and the database schema.

This is the plan with the most "decide, then freeze" work. Anything left open here gets re-argued in every
later plan.

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #88 | Write Dockerfiles per service and a single Docker Compose stack | Ayush | Infrastructure | 25 | Aug 14 |
| #89 | Provision Kafka as a Render private service with persistent disk | Ayush | Infrastructure | 15 | Aug 14 |
| #28 | Specify auction lifecycle state machine as a transition table | Sumit | Auction Orchestration | 20 | Aug 14 |
| #50 | Define bid-event schema for the fraud stream | Harshal | Fraud Detection | 12 | Aug 14 |
| #18 | Publish Bid Processing service contract and interface spec | Naitik | Bid Processing | 10 | Aug 14 |
| #103 | **Milestone: Setup phase integrated** | Ayush | Milestones | – | Aug 14 |

## What we will do

### 1. Repository and conventions (whole team, day 1–2)
- Create one monorepo, for example `services/<name>/`, `frontend/`, `contracts/`, `infra/`, `docs/adr/`, `tests/`.
- Agree on the service list from SDD Fig. 2.2: auth-user, kyc, auction-orchestrator, bid, pricing,
  payment-escrow, dispute, search-analytics, admin-moderation, ws-gateway, and the workers
  (fraud-detector, batch-flusher/projections, escrow-sweep cron). Record which schema each service owns.
- Set up branch protection on `main` (2 approvals, CI must pass), a PR template, and commit conventions.
- Agree on the Python tooling: Python 3.11, FastAPI, Pydantic v2, ruff (lint), pytest with coverage, and
  **money as decimal strings** everywhere, never floats (SDD §7.3).
- Build a **service template** (cookiecutter or a copied skeleton) with `/healthz`, `/readyz`, a `/metrics`
  stub, structured logging with `request_id`, the uniform **error envelope** (`code`, `message`,
  `details`, `request_id`) and the `/api/v1` prefix. Every service starts from this template.

### 2. Local environment — Ayush (#88)
- A Dockerfile per service, built from the template.
- One `docker-compose.yml` containing all services plus Kafka (single broker), PostgreSQL 15, Redis 7 and
  SeaweedFS (S3-compatible; MinIO no longer publishes images), with restart policies and health checks.
- Seed fixtures and a `make up` / `make down` / `make seed` workflow.
- Verify on at least two team laptops that a fresh clone comes up without any manual steps.

### 3. Kafka on Render — Ayush (#89)
- Render has no managed Kafka, so we deploy Kafka as a private service with a persistent disk **now**, not
  at deploy time (proposal risk table).
- Smoke test: produce and consume a test message, restart the service, and confirm the message and offset
  survive the restart.
- Document the fallback (an external managed cluster) in case this fails.

### 4. Auction lifecycle state machine — Sumit (#28)
- Write the transition table from SDD Table 6.1:
  DRAFT → SCHEDULED → OPEN ⇄ EXTENDED → CLOSING → CLOSED → SETTLED, plus CANCELLED, with every
  guard: KYC VERIFIED and not suspended to publish, `opens_at` reached, the anti-snipe guard interval and
  `extension_count` cap, `closes_at` reached with the bid queue drained, settle-exactly-once, and cancel only
  with no accepted bids.
- Also draft the **order settlement table** (SDD Table 6.2: INVOICED → CAPTURED → IN_ESCROW → SHIPPED →
  DISPUTED → RELEASED/REFUNDED) because the proposal's risk mitigation says *every* transition is
  specified in week 1.
- Output: `docs/state-machines.md`, which the team reviews and signs off.

### 5. Bid-event schema — Harshal (#50)
- Freeze `BidAccepted v1` (SDD Listing 7.7): `event_id`, `schema_version`, `auction_id` (partition key),
  `bidder_id`, `amount` (string), `server_seq`, `accepted_at`, `idempotency_key`, `device_fingerprint`.
- Agree it jointly with Sumit (producer) so that one stream feeds both bidding and fraud detection.
- Also draft `SettlementStep v1` and `ShillAlert v1` (SDD Listing 7.8) and put them in `contracts/events/`.
- Write down the topic config: `bid.events` 12 partitions/7 d, `auction.events` 6/7 d,
  `payment.events` 6/30 d compacted, `fraud.alerts` 3/30 d.

### 6. Bid service contract — Naitik (#18)
- Publish the OpenAPI for `POST /api/v1/auctions/{id}/bids` (SDD Listing 7.2): a required `Idempotency-Key` header,
  a 202 response with `bid_id`, `server_seq`, `current_price`, `min_next_bid` and `accepted_at`, and error responses
  402/403/409/422/503.
- Include the first draft of the **rejection taxonomy** (SDD Table 5.1), because the frontend and third parties
  code against it.
- Define the two synchronous dependencies Bid Processing needs (auction state, which becomes CT-1, and min
  increment, which becomes CT-3) so the orchestrator and pricing owners know what to provide.

### 7. Architecture doc, DB schema, and settlement policy (unticketed; required by the milestone)
These are part of milestone #103 but have no Jira task. Proposed split:
- **Architecture doc**: Sumit (Documentation owner) condenses SDD chapters 2–3 into `docs/architecture.md`.
- **DB schema**: each owner drafts DDL for their schema (SDD Fig. 4.2 and §4.2.1). Key constraints to get
  right now: `bids (auction_id, server_seq)` unique, `bids.idempotency_key` unique, `users.kyc_status`
  mirror, `kyc_documents` storing an object key and never a URL, an **append-only `escrow_ledger`** with a partial unique
  index on `order_id WHERE entry_type IN ('RELEASE','REFUND')`, and the audit tables.
  Sagar, Jaydip, Gaurang and Jay have no sprint-1 tickets, so they draft the KYC, payment/ledger,
  search and admin/dispute schemas respectively.
- **Settlement policy**: Jaydip plus Sumit fix the flat fee amount, currency, protection window (7 d) and fee
  treatment on refund (SDD Table 6.3). This becomes the `fee_config` row with a `fee_version`.
- **ADR-0 decisions** (see the README's open decisions): Razorpay or Stripe, FCM/Cloudinary in or out, and
  a template for ADRs 1–8 (SDD §2.6).

### 8. CI skeleton (milestone item; the full CI is #90 in Plan 2)
- A minimal GitHub Actions workflow that runs ruff and pytest on every PR, so nothing lands without a
  check from day one.

## Pull-forward (to smooth later overloads)
- **Gaurang** (0 h this plan, 100 h in Plan 3): scaffold the React 18 + Vite + Tailwind app and the routing
  shell, and read SDD chapter 8 mockups.
- **Jay** (0 h this plan): start the design tokens (SDD Fig. 8.1) to get ahead of #78.
- **Jaydip** (0 h this plan, 80 h in Plan 4): define the `PaymentPort` interface on paper and spike the chosen
  provider's test-mode manual-capture API.

## Definition of done / integration gate (#103)
- [ ] A fresh clone plus `docker compose up` brings up every container healthy, with no manual steps
- [ ] Kafka on Render is smoke-tested with persistence across a restart
- [ ] Auction and order transition tables are signed off by the team
- [ ] `BidAccepted v1`, `SettlementStep v1` and `ShillAlert v1` are committed under `contracts/`
- [ ] The bid service OpenAPI and the rejection taxonomy draft are published
- [ ] Per-service DB schemas are drafted and reviewed, including the ledger and bids constraints
- [ ] The settlement policy numbers and `fee_config` are fixed and recorded in an ADR
- [ ] The payment provider and third-party API decisions are recorded in an ADR
- [ ] The CI skeleton runs lint and tests on PRs, and branch protection is on

## Risks this window
| Risk | Mitigation |
|---|---|
| Kafka on Render fails or is flaky | Smoke-test it this week and document the external managed-cluster fallback |
| Contracts drift after they're "frozen" | Contracts live in `contracts/`, and any change needs a PR approved by the interface owner |
| Laptops can't run the full stack | Measure memory use now and document a `compose` profile for a reduced stack |
