# ZeoAuction — architecture overview

| | |
|---|---|
| **Owner** | Sumit (Documentation) |
| **Status** | Plan 1 baseline. The full design is `project_docs/system_design_ZA.pdf` (SDD v1.0) |

This is the working summary of SDD chapters 2–4, with the decisions Plan 1 added. Read it before you
touch a service. Where this document and the SDD disagree, the difference is intentional and is
listed at the end.

## 1. Services

| Service (`services/…`) | Kind | Owner | Schema | Local port |
|---|---|---|---|---|
| `auth-user` | API | Ayush | `auth` | 8001 |
| `kyc` | API | Sagar | `kyc` | 8002 |
| `auction-orchestrator` | API | Sumit | `auction` | 8003 |
| `bid` | API | Naitik | `bid` | 8004 |
| `pricing` | API | Sagar | `pricing` | 8005 |
| `payment-escrow` | API | Jaydip | `payment` | 8006 |
| `dispute` | API | Jay | `dispute` | 8007 |
| `search-analytics` | API | Sagar | `search` | 8008 |
| `admin-moderation` | API | Jay | `admin` | 8009 |
| `ws-gateway` | API + WebSocket | Ayush | `notify` | 8010 |
| `fraud-detector` | Worker | Harshal | `fraud` | 8011 (health) |
| `bid-flusher` | Worker | Sumit | `bid` (shared role) | 8012 (health) |
| `escrow-sweep` | Cron (every 60 s) | Naitik | none (reads `payment.orders`) | – |

That's the thirteen deployable services in SDD Fig. 2.2. The **gateway middleware** (auth, role gating and
`kyc_status` gating) isn't a separate deployable. It's a shared FastAPI dependency owned by Ayush (#95),
applied once per service, so no service reimplements the checks.

Every service is created from `libs/zeo-common` and provides `/healthz`, `/readyz` and `/metrics`, JSON
logs with a request id, the uniform error envelope, and API docs at `/api/v1/docs`.

## 2. Integration styles

**Synchronous (REST)** is used only where the caller cannot proceed without an answer. There are exactly four of these boundaries (CT-4 added in Plan 4), each
circuit-broken with a declared fallback and covered by a contract test:

| Id | Boundary | Breaker opens | Fallback |
|---|---|---|---|
| CT-1 | Bid → Auction Orchestration (`GET /auctions/{id}/state`) | 5 failures / 10 s | Cached state under 2 s old, else `AUCTION_STATE_UNAVAILABLE` |
| CT-2 | Auction Orchestration → KYC listing gate | – | Gate reads the JWT `kyc_status` claim, so there's no call on the hot path (ADR-0005) |
| CT-3 | Bid → Pricing (`GET /pricing/{id}/min-increment`) | 5 failures / 10 s | Last cached increment; bid flagged `increment_stale` |
| CT-4 | Orchestration → Payment (`POST /internal/orders`, open the order, S1) | 3 failures / 30 s | Auction stays `CLOSED`; the lifecycle timer retries with the same `Idempotency-Key` |
| – | Payment → provider (capture, S2) | 3 failures / 30 s | Order parked in `AWAITING_CAPTURE_RETRY`; the settlement worker retries with the same key |

**Asynchronous (Kafka)** is used for everything else. See [`contracts/events/topics.yaml`](../contracts/events/topics.yaml).
`bid.events` is keyed by `auction_id`, so all bids for one auction are on one partition in `server_seq`
order. This is what makes replay deterministic and in-flight fraud scoring cheap.

## 3. Data ownership

One PostgreSQL instance, **one schema and one login role per service**. Tables are created by the superuser,
and service roles hold only the privileges granted in `infra/postgres/init/*.sql`, so the boundary is
enforced by the database and not only by convention. No cross-schema foreign keys exist; references are
plain UUIDs.

**Documented exceptions**. Each one is granted explicitly, narrowly, and for a stated reason:

| Role | Privilege | Why |
|---|---|---|
| `kyc_svc` | `UPDATE (kyc_status, kyc_status_updated_at, token_version)` on `auth.users` | The KYC service is the only writer of the claim mirror (SDD 4.2.1) |
| `sweep_svc` | `SELECT (id, state, protection_window_ends_at)` on `payment.orders` | The sweep scans for expired windows, then releases through the Payment API |
| `kyc_svc`, `dispute_svc`, `payment_svc` | `INSERT` on `admin.audit_log` | Admin actions happen in those services, and the audit sink is append-only |

**Append-only tables** (no UPDATE/DELETE grant, plus a trigger that also stops the owner): `payment.escrow_ledger`,
`admin.audit_log`, `kyc.kyc_state_transitions`, `auction.auction_state_transitions`.
`infra/postgres/verify-guards.sql` (`make verify-db`) proves these guarantees against a running database.

**Redis** keys (SDD Table 4.3): `price:{auction_id}`, `seq:{auction_id}`, `idem:{key}`, `inc:{auction_id}`,
`ws:room:{auction_id}`, `flush:pending`. None of them is authoritative; all can be rebuilt from Kafka and PostgreSQL.

**Object storage** (SeaweedFS S3 gateway locally, S3-compatible when hosted): buckets `kyc-documents` and `dispute-evidence` are
encrypted at rest; `listing-images` isn't. Tables store object keys, never URLs.

## 4. Environments

| Environment | Composition | Authoritative for |
|---|---|---|
| Local | `docker compose up`: all services, Kafka, PostgreSQL, Redis, SeaweedFS (S3), seed data, mock payment adapter | Development and functional demos |
| CI | The same Compose file, ephemeral | Unit, contract and end-to-end results |
| Render | Blueprint (`render.yaml`), managed PostgreSQL and Key Value, Kafka as a private service with a disk | Hosted behaviour and resilience demos |
| Load-test host | Dedicated 8 vCPU / 16 GB machine | Every performance number used for acceptance |

## 5. Differences from the SDD (intentional)

| SDD says | We do | Reason |
|---|---|---|
| `auctions.search_vector` with a GIN index | `search.auction_index.search_vector`, a projection owned by Search | Search may not read `auction.auctions`; the projection is built from events |
| Auction parked in `AWAITING_CAPTURE_RETRY` (6.5) | That state lives on the **order**; the auction stays `CLOSED` | Matches SDD Table 2.2 and keeps Table 6.1 unchanged |
| `CLOSING` → `CLOSED` in one step | Two events: `close`, then `drained` | Makes "bid queue drained" an explicit, testable guard |
| Payment provider: Stripe, `POST /webhooks/stripe`, server-side capture at close | **Razorpay test mode, INR** (ADR-0009): the winner pays in Checkout, then we capture; `POST /webhooks/razorpay` | Matches the proposal; Razorpay can't charge a buyer off-session without mandates. `PaymentPort` isolates the choice |
| No notification store named | `notify.notifications`, owned by `ws-gateway` | Backs `GET /api/v1/notifications` (SDD 7.2) |
