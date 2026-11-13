# Plan 2 — Bid Service MVP

| | |
|---|---|
| **Weeks** | 3–5 (3 weeks; see note) |
| **Dates** | Mon Aug 17 – Fri Sep 4, 2026 |
| **Jira sprint** | sprint-2 |
| **Milestone** | #104 *Bid Service MVP integrated* (owner: Naitik) |
| **Checkpoint** | #111 Week-5 written progress note and hours audit (owner: Sumit) |
| **Proposal phase** | Bid Service MVP — bid validation, conflict resolution, Kafka topics, Redis buffer, auth service, labelled fraud dataset generator |

> This plan runs three weeks because the Jira sprint and the milestone both end on Sep 4.

## Goal

By Sep 4, a logged-in user can place a bid over REST against a seeded auction, and the platform does
everything on the SDD hot path (§5.1.1): idempotency check → validation → `server_seq` allocation →
Redis compare-and-set → batch buffer + publish to `bid.events` → 202 acknowledgement. Simultaneous equal
bids always resolve the same way. In parallel, JWT auth works end to end, CI is enforcing the quality gates,
and the labelled fraud dataset exists **before any detector does**.

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #19 | Implement bid validation: eligibility, funds, auction-open checks | Naitik | Bid Processing | 30 | Aug 28 |
| #20 | Implement deterministic server-side conflict resolution for concurrent bids | Naitik | Bid Processing | 35 | Sep 4 |
| #29 | Design Kafka topics and implement bid-event producer | Sumit | Bid Processing | 20 | Aug 28 |
| #30 | Implement Redis current-price buffer with batched persistence | Sumit | Bid Processing | 25 | Sep 4 |
| #31 | Add idempotency-key handling to bid submission | Sumit | Bid Processing | 10 | Sep 4 |
| #51 | Build labelled synthetic dataset generator: 500 auctions, 200 shill rings | Harshal | Fraud Detection | 18 | Sep 4 |
| #78 | Build shared component library and design tokens | Jay | Frontend | 25 | Sep 4 |
| #79 | Build login, registration, and profile screens | Jay | Auth | 20 | Sep 4 |
| #90 | Build GitHub Actions CI: lint, test, image build per PR | Ayush | Infrastructure | 15 | Sep 4 |
| #91 | Implement JWT issuance with access and refresh token rotation | Ayush | Auth | 15 | Sep 4 |
| #104 | **Milestone: Bid Service MVP integrated** | Naitik | Milestones | – | Sep 4 |
| #111 | **Checkpoint: week-5 progress note + hours audit** | Sumit | Milestones | – | Sep 4 |

## What we will do

### Bid Processing — Naitik (owner), Sumit
**Weeks 3–4 (to Aug 28)**
- **Bid validation (#19)**: the four FR-BID-2 checks: account eligible (not suspended, not the seller → `SELF_BIDDING_FORBIDDEN`),
  sufficient funds (`INSUFFICIENT_FUNDS`), auction OPEN or EXTENDED (`AUCTION_NOT_OPEN`), and amount ≥ current
  price + min increment (`BID_BELOW_INCREMENT`). Reject **before any state change**. Until the pricing engine and
  orchestrator exist, these checks call stubs that already have the published contract shapes (CT-1, CT-3).
- **Kafka producer (#29)**: create the topics as frozen in Plan 1, with `bid.events` keyed by `auction_id`. The publish
  must be acknowledged by the broker before we acknowledge the client.

**Weeks 3–5 (to Sep 4)**
- **Conflict resolution (#20)**: `SequenceAllocator` uses Redis `INCR seq:{auction_id}` to fix order before
  persistence. `ConflictResolver` does a compare-and-set on `price:{auction_id}`. The loser is re-validated against the
  new price and either accepted at the next `server_seq` or rejected. Replaying the log must produce the
  same winner (ADR-1).
- **Redis buffer and batched persistence (#30)**: `price:{id}` is the hot read; accepted bids go to `flush:pending`,
  which is bounded by **size and age**, and a flusher writes batches to PostgreSQL. Kafka is the recovery source,
  so the design rebuilds an unflushed batch by replaying from the last persisted `server_seq` (ADR-2).
- **Idempotency (#31)**: `SETNX idem:{key}` with a 24 h TTL, backed by the unique `bids.idempotency_key` column. A
  retry returns the original result.
- Write a **concurrency unit test**: N equal bids fired at the same instant always produce the same winner
  across 100 replays. This is a small forerunner of the Plan 3 harness (#22).

### Auth — Ayush (backend), Jay (screens)
- **JWT (#91)**: 15-minute access tokens and rotating refresh tokens, with rotation recorded so a replayed refresh
  token is detected. Claims are `sub`, `role`, `kyc_status` and `suspended` (ADR-5).
- **Unticketed but needed**: auth-user service endpoints: `POST /auth/register|login|refresh|logout`,
  `GET/PATCH /users/me` (SDD §7.2).
- **Screens (#79)**: login, registration and profile, built from the component library. Registration collects no
  KYC documents and shows the escrow-simulation notice (SDD §8.9).

### Frontend foundations — Jay
- **Component library and tokens (#78)**: the token set from SDD Fig. 8.1 (colours pre-checked for 4.5:1 contrast,
  spacing, type), plus primitives: button, input, card, badge/status pill, modal, toast, table, file-drop, banner.
  Every later screen is assembled from these.

### CI — Ayush (#90)
- A PR pipeline: ruff lint → pytest with an **80% coverage floor** → per-service Docker image build. Contract tests and
  the end-to-end stage get stub steps now and are filled in during Plan 7.
- Merges are blocked on lint errors or low coverage (AC-15).

### Fraud dataset — Harshal (#51)
- A generator for **500 synthetic auctions containing 200 labelled shill rings**, emitting `BidAccepted v1` events
  so the same data can be replayed into Kafka later.
- Ring patterns are parameterised (seller-linked accounts, shared fingerprints, bid velocity, inter-arrival
  regularity) so the Section 10 recall and precision can be measured from the first detector iteration (ADR-8).
- Output: a seeded, reproducible dataset plus a labels file checked into `tests/fixtures/fraud/`.

### Auction orchestration (unticketed prerequisite) — Sumit
- A minimal auction record and `GET /auctions/{id}/state` (internal, CT-1) so bid validation has a real state to
  read. Full guards come in Plan 3 (#24).

### Week-5 checkpoint — Sumit (#111)
- Written progress note: what's integrated, what's slipping, and hours logged per member against plan.
- **Reassign work if any member is off plan by more than 15%.**

## Pull-forward (to smooth later overloads)
- **Gaurang** (0 h here, 100 h in Plan 3): build the auction detail and bid form layout (#69) against the
  frozen bid contract with mocked responses, and spike the WebSocket client with a mock server (#71).
- **Sagar** (0 h here, 55 h in Plan 3): draft the KYC endpoints and verification state machine on paper (SDD Fig. 6.3).
- **Jaydip** (0 h here): start `PaymentPort` + `MockPaymentAdapter` (#59) early.

## Definition of done / integration gate (#104)
- [ ] `POST /api/v1/auctions/{id}/bids` returns 202 with `server_seq` and `current_price` on the Compose stack
- [ ] All four validation rules reject with the correct taxonomy code before any state change
- [ ] Equal concurrent bids resolve to an identical winner on replay
- [ ] Idempotent retry returns the original result and creates no second row
- [ ] Accepted bids appear on `bid.events`, partitioned by `auction_id`
- [ ] Redis buffer flushes to PostgreSQL by size and by age; crash recovery by Kafka replay is demonstrated
- [ ] Register → login → refresh → `/users/me` works end to end; the auth screens use the component library
- [ ] CI blocks merges on lint errors or coverage below 80%
- [ ] The fraud dataset generator produces 500 auctions / 200 labelled rings reproducibly
- [ ] The week-5 progress note and hours audit are published

## Risks this window
| Risk | Mitigation |
|---|---|
| Redis CAS + batching is harder than planned | Naitik and Sumit pair on it; keep the batch bounded; Kafka stays the recovery source |
| Validation blocked on orchestrator/pricing services that don't exist yet | Code against the frozen CT-1/CT-3 contract shapes with stubs |
| Hot-path latency unknown | Add `bid_ack_latency_seconds` histogram now so Plan 4's baseline has data |
