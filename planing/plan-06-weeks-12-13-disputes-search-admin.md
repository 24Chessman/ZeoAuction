# Plan 6 — Disputes, Search & Admin

| | |
|---|---|
| **Weeks** | 12–13 |
| **Dates** | Mon Oct 19 – Fri Oct 30, 2026 |
| **Jira sprint** | sprint-6 |
| **Milestone** | #108 *Disputes, Search and Admin integrated* (owner: Jay) |
| **Checkpoint** | #113 Week-13 written progress note and hours audit (owner: Sumit), the final audit before testing |
| **Proposal phase** | Disputes, Search & Admin — dispute lifecycle and window enforcement, auto-release scheduler, adjudication console, refunds, full-text search, seller dashboard, fraud tuning |

## Goal

By Oct 30 the **buyer-protection story is complete**. Every order that enters escrow ends in exactly
one terminal state through one of the defined paths:
- **Release (a):** the buyer confirms receipt, and the funds release immediately.
- **Release (b):** the protection window expires with no dispute, and the cron sweep releases within 5 minutes.
- **Release (c):** an admin adjudicates in the seller's favour.
- **Refund:** an admin adjudicates in the buyer's favour, and the fee treatment follows the chosen fault.

Fraud can open disputes automatically with linked evidence. Search, the seller dashboard, the notification tray and
admin moderation (listings, suspension, immutable audit log) are all in place. **This is the last feature
plan**: after Oct 30 we only test, deploy and document.

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #84 | Specify dispute lifecycle and build admin adjudication console | Jay | Dispute Mgmt | 35 | Oct 30 |
| #81 | Build listing review and moderation queue | Jay | Admin | 25 | Oct 30 |
| #82 | Build user suspension workflow | Jay | Admin | 15 | Oct 30 |
| #83 | Build immutable audit log | Jay | Admin | 20 | Oct 30 |
| #65 | Implement escrow release execution for all three triggers | Jaydip | Payment | 25 | Oct 30 |
| #66 | Implement refund execution and ledger reconciliation | Jaydip | Dispute Mgmt | 25 | Oct 30 |
| #35 | Implement escrow release and refund terminal transitions | Sumit | Auction Orchestration | 15 | Oct 30 |
| #25 | Build protection-window timer and auto-release scheduler | Naitik | Dispute Mgmt | 25 | Oct 30 |
| #97 | Configure Render Cron job runner for the escrow sweep | Ayush | Infrastructure | 10 | Oct 30 |
| #55 | Implement bid-ring clustering | Harshal | Fraud Detection | 30 | Oct 30 |
| #56 | Implement fraud-triggered dispute creation and evidence linkage | Harshal | Dispute Mgmt | 20 | Oct 30 |
| #46 | Build PostgreSQL full-text search indexing | Sagar | Search | 15 | Oct 30 |
| #47 | Build search and filter query API | Sagar | Search | 15 | Oct 30 |
| #73 | Build dispute submission form with evidence upload | Gaurang | Frontend | 25 | Oct 30 |
| #74 | Build notification tray for outbid, KYC, and dispute events | Gaurang | Frontend | 20 | Oct 30 |
| #75 | Build seller dashboard: listings, sales, payout status | Gaurang | Search | 25 | Oct 30 |
| #108 | **Milestone: Disputes, Search and Admin integrated** | Jay | Milestones | – | Oct 30 |
| #113 | **Checkpoint: week-13 progress note + hours audit** | Sumit | Milestones | – | Oct 30 |

## What we will do

### Dispute lifecycle — Jay (owner), Naitik, Harshal, Gaurang
- **Lifecycle spec + adjudication console (#84)**: dispute states (OPEN → UNDER_REVIEW → RESOLVED_SELLER /
  RESOLVED_BUYER). `POST /orders/{id}/disputes` accepts reason codes ITEM_NOT_RECEIVED, NOT_AS_DESCRIBED,
  DAMAGED_IN_TRANSIT, COUNTERFEIT and OTHER, and a request against a closed window is **refused with `WINDOW_CLOSED` (409)**
  (AC-11). Opening a dispute **freezes escrow**. The console (SDD Fig. 8.7) shows the case, evidence, seller response
  and audit history. `POST /admin/disputes/{id}/resolve` takes `outcome` and `fault` as **separate** inputs, and the fee
  treatment is derived automatically from the fault (SDD Table 6.3).
- **Dispute Management never writes the ledger.** It sends freeze, release and refund commands to Payment
  over a published contract (SDD §5.2.4).
- **Window timer + auto-release (#25, Naitik)**: the protection window starts at `markShipped` and defaults to 7 days. The sweep
  scans `orders(protection_window_ends_at) WHERE state = SHIPPED` (partial index) and releases expired
  holds **within 5 minutes** (AC-12). After that, the dispute option is permanently closed.
- **Cron runner (#97, Ayush)**: the sweep runs as a **Render Cron Job**, not an in-process timer, because an idle instance
  would silently skip it (ADR-6). It's idempotent, so overlapping runs are safe. Expose the
  `escrow_sweep_lag_seconds` metric and alert above 300 s.
- **Fraud-triggered disputes (#56, Harshal)**: a flagged auction opens a dispute with `opened_by = FRAUD_SERVICE`,
  links `fraud_alerts.dispute_id`, attaches the **bid trace** as evidence, and **blocks settlement** pending review.
- **Dispute form (#73, Gaurang)**: enabled only while the window is open, and read-only with the closing date after
  that. Evidence uploads go to object storage. The form shows the fee outcome per fault before submission (SDD Fig. 8.6).

### Release and refund — Jaydip (owner), Sumit
- **Release, all three triggers (#65)**: buyer confirm (`POST /orders/{id}/confirm-receipt`), sweep expiry, and
  adjudication for the seller. All three converge on the same RELEASE ledger write (net = captured − fee) with
  the `order:{id}:release` idempotency key.
- **Refund + reconciliation (#66)**: reverse the capture through the provider. Buyer fault means the fee is retained; seller or platform
  fault means the fee is refunded in full. A reconciliation routine asserts the SDD §4.3.2 invariants per order.
- **Terminal transitions (#35, Sumit)**: RELEASED and REFUNDED are terminal. Any later event is refused and no new dispute
  can be opened (FR-AO-6).

### Admin & moderation — Jay
- **Audit log (#83)**: an append-only `audit_log` (actor, before/after state, reason code) with **no UPDATE/DELETE grant**.
  Build this **first**, because the adjudication console, suspension and KYC review all write to it.
- **Listing review queue (#81)**: review new and reported listings.
- **Suspension (#82)**: reason codes, blocks re-listing, updates the JWT claim through a forced refresh.
- **Unticketed**: `GET /admin/metrics/daily`, `POST /admin/broadcasts`, `GET /admin/audit-log`.

### Search & seller dashboard — Sagar, Gaurang
- **Indexing (#46)**: a stored `auctions.search_vector` tsvector with a GIN index, refreshed incrementally on listing
  change (an event consumer).
- **Query API (#47)**: `GET /search/auctions` with `q`, `category`, `price_min`/`price_max`, `status`, `sort`
  (ending_soonest, newest, price_asc, price_desc) and `page`/`page_size` (max 100) (SDD Listing 7.6).
- **Seller dashboard (#75, Gaurang)**: listings, sales, and escrow state per order that mirrors `orders.state` exactly.
  The expected release date is `shipped_at` + the window. It shows the simulation notice (SDD Fig. 8.5).
- **Browse/search screen** (unticketed, SDD Fig. 8.2): faceted filters, with "flat fee applies on win" on each card.

### Notifications — Gaurang (#74)
- A tray for outbid, KYC status, dispute, payout and admin broadcast events, delivered over the platform's own WebSocket
  `notification` message plus `GET /notifications` for history (unticketed endpoint).

### Fraud tuning — Harshal (#55)
- **Bid-ring clustering**: cluster colluding accounts across auctions using fingerprints and the bidder/seller
  graph. Feed the cluster confidence into the alert (`ring_id`) and into the adjudication console's bid trace.
- Re-measure recall and precision on the dataset after clustering is added.

### Week-13 checkpoint — Sumit (#113)
- Final hours audit before testing. **Declare feature freeze on Oct 30.** Anything not done moves to a
  documented "known gaps" list rather than into the testing window.

## Load warning and pull-forward
- **Jay has 95 h here**, the heaviest window on the project. The audit log (#83) and dispute spec (#84) should be
  started in Plan 5 week 11. If Jay is behind, split the work: Naitik (25 h here) or Sumit (15 h) takes the
  suspension workflow (#82), since it's mostly backend.
- **Gaurang has 70 h.** Start the dispute form (#73) in Plan 5 week 11 against the SDD contract.

## Definition of done / integration gate (#108)
- [ ] Buyer confirms receipt → immediate release; the ledger shows RELEASE = captured − fee
- [ ] Window expires with no dispute → cron sweep releases within 5 minutes; a dispute after that gets `WINDOW_CLOSED`
- [ ] Buyer opens a dispute in the window → escrow frozen → admin resolves for the seller → release
- [ ] Admin resolves for the buyer with fault = SELLER/PLATFORM → full refund incl. fee; fault = BUYER → fee retained
- [ ] No order ever gets both a RELEASE and a REFUND (the database index refuses it)
- [ ] The fraud detector opens a dispute with a linked bid trace and settlement is blocked
- [ ] Every admin action appears in the immutable audit log
- [ ] Search returns filtered, paginated results via the GIN index
- [ ] The seller dashboard shows escrow state and the expected payout date
- [ ] The notification tray receives outbid, KYC and dispute events live
- [ ] The week-13 progress note, hours audit and feature freeze are published

## Risks this window
| Risk | Mitigation |
|---|---|
| Escrow and dispute states grow the state machine | They were specified in Plan 1; the time-accelerated fixture exercises every terminal path |
| A retried command causes a double release | Idempotency keys + the partial unique index on the ledger, so the database is the last line of defence |
| The feature window overruns into testing | Hard feature freeze on Oct 30; leftovers go to a known-gaps list |
