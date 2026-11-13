# Plan 4 — Pricing, Payments & Fees

| | |
|---|---|
| **Weeks** | 8–9 |
| **Dates** | Mon Sep 21 – Fri Oct 2, 2026 |
| **Jira sprint** | sprint-4 |
| **Milestone** | #106 *Pricing, Payments and Fees integrated* (owner: Jaydip) |
| **Checkpoint** | #112 Week-9 written progress note and hours audit (owner: Sumit) |
| **Proposal phase** | Pricing, Payments & Fees — pricing engine, payment provider integration, convenience-fee calculation, escrow hold, Saga compensation paths, **baseline load measurement** |

## Goal

By Oct 2, an auction can **close and settle**: the orchestrator generates an invoice for the winning bid
plus the flat fee, the payment service captures the total through the provider (test mode, manual
capture), and the money sits in an **append-only escrow ledger** as a hold. Bid increments are now dynamic,
driven by a real pricing engine. We also take the **first baseline load measurement**, six weeks
before the final demo, so any performance gap is known early.

> **Decided 2026-10-10 (ADR-0009, ADR-0011):** the provider is **Razorpay test mode** and the currency **INR**,
> with a flat fee of **₹99.00** (`fee_version 2026-10-v1`). Razorpay can't charge the winner off-session, so the
> winner pays the invoice in Razorpay Checkout. That adds an `AUTHORIZED` step between `INVOICED` and `CAPTURED`
> (`docs/state-machines.md`, O1a) and a 48 h payment window. Orchestration hands closed auctions to Payment over the
> new internal contract **CT-4**. Read "Stripe" below as "Razorpay".

> **Status 2026-10-10:** all tickets implemented in the working tree and unit-tested (see `docs/progress/week-09.md`).
> The gate below stays unticked until each item has run on the Compose stack. #23's tuning is deferred until the
> host run (`docs/perf/week-09-baseline.md`).

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #33 | Implement settlement transition: close → invoice → capture → escrow hold | Sumit | Auction Orchestration | 30 | Oct 2 |
| #34 | Implement invoice generation with flat convenience fee | Sumit | Payment | 25 | Oct 2 |
| #42 | Implement bid-velocity tracking | Sagar | Pricing Engine | 25 | Oct 2 |
| #43 | Implement dynamic bid increment calculation | Sagar | Pricing Engine | 30 | Oct 2 |
| #44 | Implement hot-auction flagging and thresholds | Sagar | Pricing Engine | 20 | Oct 2 |
| #60 | Integrate Stripe (or Razorpay, per the ADR) test mode with manual capture | Jaydip | Payment | 30 | Oct 2 |
| #61 | Build flat convenience-fee engine with disclosure API | Jaydip | Payment | 20 | Oct 2 |
| #62 | Build escrow ledger and hold transition | Jaydip | Payment | 30 | Oct 2 |
| #52 | Build streaming consumer scaffold on the bid topic | Harshal | Fraud Detection | 20 | Oct 2 |
| #23 | Tune conflict resolution against week-9 load baseline | Naitik | Bid Processing | 10 | Oct 2 |
| #106 | **Milestone: Pricing, Payments and Fees integrated** | Jaydip | Milestones | – | Oct 2 |
| #112 | **Checkpoint: week-9 progress note + hours audit** | Sumit | Milestones | – | Oct 2 |

## What we will do

### Payment, fees and escrow — Jaydip (owner), Sumit
- **Fee engine + disclosure (#61)**: a `fee_config` singleton with a `fee_version`, fixed in Plan 1.
  `GET /api/v1/fees/quote?bid_amount=` returns `bid_amount`, `convenience_fee`, `total`, `currency` and `fee_version`
  (SDD Listing 7.3). The quote is **the same value** used at invoice time; it isn't an estimate. This replaces the
  frontend stub from Plan 3.
- **Provider adapter (#60)**: the second implementation of `PaymentPort`, using **test mode only, synthetic accounts, no
  real funds**. Manual capture is the escrow primitive: the payment is authorised, then captured into platform custody.
  The provider (Stripe or Razorpay) is whatever the Plan 1 ADR decided.
- **Escrow ledger + hold (#62)**: `escrow_ledger` is **append-only**, with no UPDATE or DELETE grant. Entry types are
  CAPTURE, HOLD, FEE_RETAIN, RELEASE, REFUND and COMPENSATION (SDD Table 4.2). Add the partial unique index so a second
  RELEASE/REFUND for an order is refused by the database. No code path pays a seller outside the release
  transition.
- **Invoice (#34, Sumit)**: invoice = winning bid + flat fee. Losing bidders are **never** invoiced (AC-09).
- **Settlement transition (#33, Sumit)**: CLOSED → S1 create order and invoice → S2 authorise and capture → S3 write
  CAPTURE, HOLD and FEE_RETAIN rows → S4 `orders.state = IN_ESCROW`. Settle exactly once, enforced by a unique `orders.auction_id`.
  Emit `SettlementStep v1` to `payment.events`.
- **Circuit breaker, Orchestration → Payment** (SDD Table 2.2): after 3 failures in 30 s, park the order in
  `AWAITING_CAPTURE_RETRY` and retry with the same idempotency key. Settlement is deferred, never abandoned.
- The full Saga compensation paths are #63 in Plan 5, but **design the compensation for each step now** (SDD
  Table 5.2) so the forward path isn't built in a way that blocks them.

### Pricing engine — Sagar
- **Velocity (#42)**: a rolling bid rate per auction, fed by `bid.events`.
- **Dynamic increment (#43)**: the increment scales with velocity and current price. Serve it at
  `GET /pricing/{auctionId}/min-increment` (internal, CT-3) and cache it at `inc:{auction_id}` (60 s), which is also the
  circuit-breaker fallback.
- **Hot-auction flag (#44)**: thresholds that flag contended auctions for prioritised buffering and monitoring.
- **Circuit breaker, Bid → Pricing**: after 5 failures in 10 s, use the last cached increment and flag the batch
  `increment_stale`. Bidding continues.

### Load baseline and tuning — Naitik (#23), with Ayush
- Run the Plan 3 concurrency harness plus a first aggregate run (toward 1000 bids/s across 50 auctions).
- Compare measured p95 bid acknowledgement against the **500 ms budget** broken down in SDD Table 9.3 (gateway 40,
  idempotency 10, validation 180, sequencing/CAS 20, enqueue/publish 60, response 40, headroom 150).
- Tune conflict resolution toward the target, and **record the curve and the bottleneck** even if we miss the target.
- Official numbers come only from the dedicated 8 vCPU / 16 GB host. Laptop numbers are indicative only.

### Fraud streaming scaffold — Harshal (#52)
- A consumer group on `bid.events` with offset management and a `SlidingWindow` per auction. It's a separate
  worker, and stopping it must not affect bidding. It resumes from the retained offset.
- Replay the Plan 2 synthetic dataset through Kafka to prove the scaffold consumes it in order.

### Week-9 checkpoint — Sumit (#112)
- Second hours audit. Also confirm the **mid-semester demo script** (Oct 12) and assign a rehearsal owner.

## Load warning and pull-forward
- **Jaydip has 80 h here.** Ideally #59/#60 were started early (Plans 2–3). If Jaydip is behind, Sumit pairs on
  the ledger (#62), since Sumit is writing the settlement transition that feeds it.
- **Harshal has 70 h in week 10 (Plan 5).** Use the free time in this plan (only 20 h scheduled) to start the
  shill-detector features (#53) and the fingerprint signals (#54).
- **Gaurang and Jay have 0 h here**: use the time to wire the fee quote into the bid screen, polish the bid
  UI for the demo, start the unticketed **browse/search** screen (SDD Fig. 8.2), and have Jay start the
  audit-log schema (#83) and dispute lifecycle spec (#84) ahead of their 95 h in Plan 6.

## Definition of done / integration gate (#106)
- [ ] An auction closes → an invoice (bid + flat fee) is generated → capture runs through the provider test mode (and through the mock adapter) → the ledger holds CAPTURE, HOLD and FEE_RETAIN → the order is IN_ESCROW
- [ ] Losing bidders have no invoice
- [ ] The fee quote shown on the bid screen matches the invoice fee (same `fee_version`)
- [ ] The ledger refuses UPDATE/DELETE, and the database rejects a second RELEASE/REFUND row
- [ ] Payment down → the order is parked in `AWAITING_CAPTURE_RETRY` and recovers when payment returns
- [ ] Dynamic increments are served from the pricing engine, and the stale-increment fallback works when it's stopped
- [ ] The baseline load report is written: measured p95s vs targets, plus the identified bottleneck
- [ ] The fraud consumer scaffold replays the dataset in order and survives a restart
- [ ] The week-9 progress note and hours audit are published, and the demo script is agreed

## Risks this window
| Risk | Mitigation |
|---|---|
| Provider test-mode limits on escrow-style flows | Everything goes through `PaymentPort`, so the mock adapter carries the demo if needed |
| Performance targets look out of reach | That's why the baseline is here: report the curve honestly and decide the tuning focus for Plan 7 |
| Money rounding bugs | Decimal strings end to end; ledger invariants are unit-tested now |
