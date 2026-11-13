# Plan 3 — Identity & Real-Time

| | |
|---|---|
| **Weeks** | 6–7 |
| **Dates** | Mon Sep 7 – Fri Sep 18, 2026 |
| **Jira sprint** | sprint-3 |
| **Milestone** | #105 *Identity and Real-Time integrated* (owner: Sagar) |
| **Proposal phase** | Identity & Real-Time — seller KYC submission, admin approval, listing gate enforced; auction state machine, auto-extension, WebSocket gateway, live price push |

## Goal

By Sep 18, the platform has **identity** and **real time** working:
- A seller submits KYC documents, an admin approves them, and only then can that seller create an auction. The
  listing gate is enforced at the service layer, so calling the API directly with an unverified token is refused.
- The auction lifecycle is guarded, including anti-snipe extension.
- Watchers see price changes pushed over WebSocket in real time, and an outbid bidder is alerted.
- The bidding screen shows the live price and the flat fee before a bid is placed.

This is the plan with the **most parallel work** (7 of 8 members active), so integration discipline matters.

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #21 | Define bid rejection taxonomy and structured error responses | Naitik | Bid Processing | 10 | Sep 18 |
| #22 | Build concurrency test harness for contended single-auction bidding | Naitik | Bid Processing | 20 | Sep 18 |
| #24 | Implement auction lifecycle transition guards (bid, extend, close) | Naitik | Auction Orchestration | 30 | Sep 18 |
| #32 | Implement anti-snipe auto-extension logic | Sumit | Auction Orchestration | 20 | Sep 18 |
| #38 | Build KYC document submission endpoints and validation | Sagar | KYC | 15 | Sep 18 |
| #39 | Provision encrypted document store with time-limited signed URLs | Sagar | KYC | 15 | Sep 18 |
| #40 | Implement seller verification state machine | Sagar | KYC | 15 | Sep 18 |
| #41 | Enforce listing gate at the service layer | Sagar | KYC | 10 | Sep 18 |
| #59 | Define payment service interface with a mock adapter | Jaydip | Payment | 20 | Sep 18 |
| #69 | Build bidding UI: auction detail and bid form | Gaurang | Frontend | 30 | Sep 18 |
| #70 | Build live price display with flat fee disclosure | Gaurang | Frontend | 20 | Sep 18 |
| #71 | Integrate WebSocket client with reconnect and optimistic price updates | Gaurang | Frontend | 30 | Sep 18 |
| #72 | Build KYC document upload flow | Gaurang | Frontend | 20 | Sep 18 |
| #80 | Build admin KYC verification review queue | Jay | KYC | 20 | Sep 18 |
| #92 | Build WebSocket gateway: connection management and auth handshake | Ayush | WebSocket | 20 | Sep 18 |
| #93 | Implement room fan-out and outbid alert dispatch | Ayush | WebSocket | 15 | Sep 18 |
| #94 | Implement reconnect and backpressure handling | Ayush | WebSocket | 10 | Sep 18 |
| #95 | Build gateway middleware for role and verification-status gating | Ayush | Auth | 15 | Sep 18 |
| #96 | Configure object storage bucket with encryption and signed-URL policy | Ayush | Infrastructure | 10 | Sep 18 |
| #105 | **Milestone: Identity and Real-Time integrated** | Sagar | Milestones | – | Sep 18 |

## What we will do

### KYC & seller verification — Sagar (owner), Ayush, Jay, Gaurang
- **Storage (#96, Ayush → #39, Sagar)**: an S3-compatible bucket (SeaweedFS locally) encrypted at rest. Documents are
  read **only** through short-TTL signed URLs. We store the object key and never a URL. Document bytes never appear in logs, and
  `purge_after` records when they're deleted. Only synthetic or team-consented samples are used.
- **Submission endpoints (#38)**: `POST /kyc/submissions`, `POST /kyc/submissions/{id}/documents` (type, size and
  MIME validation), and `GET /kyc/submissions/me`.
- **Verification state machine (#40)**: SUBMITTED → UNDER_REVIEW → VERIFIED / REJECTED (recoverable, with the
  reason returned to the seller) → SUSPENDED (reversible). Every transition is written to `kyc_state_transitions` with the actor
  and a timestamp. The KYC service is the only writer of the `users.kyc_status` mirror, and a status change **forces token
  refresh**.
- **Admin review queue (#80, Jay)**: `GET /admin/kyc/queue`, approve and reject (reason code required), a document
  viewer that uses signed URLs, and opening a document is itself audited (SDD Fig. 8.8).
- **Listing gate (#41)** + **gateway middleware (#95, Ayush)**: one middleware checks `role`,
  `kyc_status` and `suspended` from the JWT, so no service reimplements it. `POST /auctions` refuses anyone who isn't
  VERIFIED with `SELLER_NOT_VERIFIED`. **The test calls the API directly with a valid unverified token**
  (AC-06), not through the UI.
- **Upload UI (#72, Gaurang)**: a status strip that mirrors the state machine, the rejected reason shown inline with
  upload re-enabled, and a "why can't I list yet" panel naming the exact API refusal (SDD Fig. 8.4).

### Auction orchestration — Naitik, Sumit
- **Transition guards (#24)**: implement SDD Table 6.1 as the single source of lifecycle truth. Illegal
  transitions are rejected explicitly. Expose `GET /auctions/{id}/state` for bid validation (CT-1).
- **Anti-snipe (#32)**: a bid inside the guard interval moves OPEN → EXTENDED and pushes `closes_at` forward;
  `extension_count` is capped. Emit to `auction.events` so the WS gateway broadcasts `auction_extended`.
- **Unticketed**: finish auction CRUD (`POST /auctions`, `publish`, `cancel`, `GET /auctions/{id}`) behind the
  listing gate.
- **Circuit breaker, Bid → Orchestration** (SDD Table 2.2): use cached state if it's less than 2 s old, otherwise
  `AUCTION_STATE_UNAVAILABLE`. Never accept a bid against an unknown state.

### Bid Processing hardening — Naitik
- **Rejection taxonomy (#21)**: finalise SDD Table 5.1 (9 codes with HTTP statuses) as a versioned,
  published vocabulary, delivered in the uniform error envelope. Adding a code is a minor version bump; changing a code's meaning is a breaking change.
- **Concurrency harness (#22)**: a reproducible rig driving **200 bids/s at one auction**, asserting identical
  winners across replays (FR-TEST-3, AC-02). This produces the numbers Plan 4 tunes against.

### WebSocket gateway — Ayush
- **Connections (#92)**: a WSS handshake authenticated with the JWT, per-connection limits, and ping/pong.
- **Fan-out (#93)**: a Kafka consumer group on `bid.events` / `auction.events` pushes `price_update` to rooms
  (`ws:room:{auction_id}`), and `outbid` goes **only** to the displaced bidder. Fan-out is driven by the consumer, not
  the request thread, so a slow watcher can't slow a bidder. Target: p95 < 100 ms with 500 watchers.
- **Reconnect and backpressure (#94)**: the client re-subscribes with its last `server_seq`, and the gateway sends a snapshot.
  When a buffer overflows, intermediate `price_update`s are coalesced (last write wins), but notifications are **never** coalesced.

### Frontend bidding — Gaurang
- **Auction detail and bid form (#69)**: client validation mirrors the rejection taxonomy exactly. The client never
  invents a rule the server doesn't enforce, and vice versa.
- **Live price + fee disclosure (#70)**: the flat fee and resulting total come from `GET /fees/quote` and are shown
  **before** the bid is placed (AC-07). Until Plan 4, the quote endpoint returns the fixed `fee_config` from
  Plan 1 through a stub.
- **WS client (#71)**: an optimistic update on submit, reconciled on acknowledgement. Frames whose `server_seq` isn't
  greater than the last one seen are discarded, and a visible reconnect banner replaces a silently frozen price.

### Payment port — Jaydip (#59)
- A `PaymentPort` interface with `authorise`, `capture`, `release` and `refund`, all carrying idempotency keys, plus a deterministic
  **`MockPaymentAdapter`** (no network, no keys). This is what keeps the demo runnable offline (ADR-7).

## Load warning and pull-forward
Gaurang has **100 h** scheduled in these two weeks. Mitigations:
- Gaurang should have started #69 and #71 against mocks in Plan 2 (see Plan 2 pull-forward). If not, Jay
  (20 h here) helps on the KYC upload flow (#72) since Jay is building the matching admin queue.
- If it slips, the priority order is #70 (fee disclosure, AC-07) → #69 → #71 → #72.

## Definition of done / integration gate (#105)
- [ ] Seller submits KYC → admin approves → token refreshes → seller creates an auction
- [ ] A direct API call with an unverified token to `POST /auctions` gets `SELLER_NOT_VERIFIED`; zero auctions created
- [ ] KYC documents are only reachable through expiring signed URLs, and no document bytes appear in logs
- [ ] Every KYC and lifecycle transition is recorded in its audit table
- [ ] Illegal auction transitions are rejected, and anti-snipe extends `closes_at` up to the cap
- [ ] Two browsers watching one auction both see price updates live, and the outbid user gets an alert
- [ ] Killing and restoring the network shows the reconnect banner, then resumes with no missed price
- [ ] The bid screen shows the flat fee and total before placing a bid
- [ ] The concurrency harness runs 200 bids/s on one auction with an identical winner on replay
- [ ] `MockPaymentAdapter` implements `PaymentPort` and has unit tests

## Risks this window
| Risk | Mitigation |
|---|---|
| Many parallel integrations land on the same days | Integration Friday of week 6 is a mid-plan merge day; the milestone owner (Sagar) runs the full flow |
| JWT claim goes stale after approval or suspension | Forced refresh on status change, and a test for it |
| WS fan-out latency unknown | Add the `ws_fanout_latency_seconds` histogram now |
