# Week-9 progress note and hours audit (#112)

| | |
|---|---|
| **Owner** | Sumit (Documentation, Milestones) |
| **Covers** | Plan 4, Pricing, Payments & Fees (weeks 8–9, Sep 21 – Oct 2) |
| **Written** | 2026-10-10. **Late**: the checkpoint was due Fri Oct 2. Plan 4's code also landed after Oct 2, in the week-10 working tree |
| **Milestone** | #106 *Pricing, Payments and Fees integrated* (owner Jaydip): **not signed off**, see §3 |

## 1. Summary

Plan 4's scope is implemented in the working tree, and every unit and contract suite passes. An auction can close and
settle: invoice (winning bid + ₹99.00 flat fee), Razorpay Checkout (test mode) or the mock adapter, manual capture,
and an append-only escrow ledger with CAPTURE, HOLD and FEE_RETAIN rows. The order is then IN_ESCROW. The pricing engine
serves dynamic increments on CT-3, Bid Processing has a breaker and stale fallback for it, the fraud scaffold consumes
`bid.events`, and the first load baseline is written.

Two things stop us from calling #106 done:

1. **Nothing in Plan 4 has run against the real stack yet.** PostgreSQL, Kafka, Redis, SeaweedFS and Razorpay test mode
   have all been replaced by fakes in tests (recording fakes of asyncpg, a scripted `httpx.MockTransport` for
   Razorpay). New SQL (`32-`, `51-`, `61-`) has never been applied to a fresh database.
2. **Plan 4 is uncommitted**, and Plans 1–3 sit on `main` as two bulk commits rather than per-member ones. The commits
   in `commits/commit-plan-04.md` still have to be made, reviewed and merged before the work counts as delivered.

Decisions taken this sprint: **ADR-0009 Accepted** (Razorpay test mode, INR) and **ADR-0011 Accepted**
(₹99.00 flat fee, `fee_version 2026-10-v1`), both 2026-10-10. ADR-0010 (third-party services) is still Proposed.

## 2. Status by ticket

| Jira | Task | Owner | Est. h | Status | Evidence |
|---|---|---|---|---|---|
| #33 | Settlement transition close → invoice → capture → escrow hold | Sumit | 30 | Done (unit level) | `payment-escrow/app/{service,worker}.py`, orchestrator CT-4 client and A7 on `HELD`; `tests/test_settlement_flow.py`, `auction-orchestrator/tests/test_settlement.py` |
| #34 | Invoice with flat convenience fee | Sumit | 25 | Done | `app/domain/invoice.py`; losers never invoiced (`tests/test_invoice.py`) |
| #42 | Bid-velocity tracking | Sagar | 25 | Done | `pricing/app/domain/velocity.py`, `bid_consumer.py`; persisted 5 s buckets |
| #43 | Dynamic bid increment + CT-3 + bid-side breaker | Sagar | 30 | Done | `pricing/app/domain/increment.py`, `app/api.py`; `bid/tests/test_ct3_breaker.py` |
| #44 | Hot-auction flagging | Sagar | 20 | Done | `pricing/app/domain/hot_auction.py` (30 / 15 bids/min hysteresis) |
| #60 | Razorpay test mode, manual capture | Jaydip | 30 | Done (no live test-mode call yet) | `payment_port/razorpay_adapter.py`, refuses non-`rzp_test_` keys |
| #61 | Flat fee engine + disclosure API | Jaydip | 20 | Done | `GET /fees/quote` from `fee_config`; the frontend shows the same `fee_version` |
| #62 | Escrow ledger + hold | Jaydip | 30 | Done (DB guards unverified) | `app/domain/ledger.py`, `61-payment-razorpay.sql`; `verify-guards.sql` not run |
| #52 | Streaming consumer scaffold | Harshal | 20 | Done (fake broker) | `fraud-detector/app/{consumer,windows}.py`, `tests/test_replay_resume.py` |
| #23 | Conflict-resolution tuning vs week-9 baseline | Naitik | 10 | Partial | `docs/perf/week-09-baseline.md` (indicative run, bottleneck identified); host run and any tuning outstanding |
| pull-forward | Audit-log writer, dispute lifecycle draft | Jay | – | Done (draft) | `zeo_common/audit.py`, `docs/dispute-lifecycle.md` |
| pull-forward | Load-test host provisioning | Ayush | – | Done (script untested on a host) | `infra/loadtest/provision.sh` |
| pull-forward | Fee quote in bid UI, Pay now, browse notice | Gaurang | – | Done | `SettlementPanel.tsx`, `BidPanel.tsx`, `AuctionsPage.tsx` |

Test evidence as of 2026-10-10: ruff clean; every Python suite passes (zeo-common, contracts and 13 services, each in
its own process); 42 frontend tests pass; coverage ≥ 80 % per service.

## 3. Gate #106

| Gate item | State |
|---|---|
| Close → invoice → capture (mock and provider test mode) → CAPTURE, HOLD, FEE_RETAIN → IN_ESCROW | Unit-tested end to end with the mock adapter; **not yet run on the stack or against Razorpay test mode** |
| Losing bidders have no invoice | Unit-tested |
| Quoted fee = invoiced fee (same `fee_version`) | Unit-tested; the frontend reads the same `config/settlement-policy.yaml` |
| Ledger refuses UPDATE/DELETE; DB rejects a second RELEASE/REFUND | SQL written; **`verify-guards.sql` not run** |
| Payment down → `AWAITING_CAPTURE_RETRY` → recovers | Unit-tested (breaker 3 / 30 s, worker retries with the same key) |
| Dynamic increments from pricing; stale fallback when it's stopped | Unit-tested both sides; Compose now runs bid with `PRICING_MODE=http` |
| Baseline load report: measured p95s vs targets, bottleneck | Indicative report written; **official host numbers missing** |
| Fraud consumer replays the dataset in order, survives a restart | Proven against a 12-partition fake; real-broker check documented, not run |
| Week-9 note + hours audit published, demo script agreed | This note; `docs/demo/mid-semester-script.md` **to be agreed at the Sunday sync** |

**To sign off #106** (Jaydip): `docker compose up`, `verify-db`, `smoke-kafka`, then one auction through close →
IN_ESCROW with the mock adapter and once with Razorpay test keys. After that, tag `plan-04`.

## 4. Hours audit (second audit)

Estimates come from Jira (`project_docs/zeoauction_jira_import (1).csv`, plan tables). **Actual hours can only come
from each member's own log; they aren't in the repository.** Fill in the "Actual" column before this note counts as
the audit. The first audit (#111, week 5) was never written, so this one also has to cover weeks 1–9 cumulatively.

| Member | Plan 4 tickets | Est. h (Plan 4) | Actual h (Plan 4) | Est. h (weeks 1–9) | Actual h (weeks 1–9) | Note |
|---|---|---|---|---|---|---|
| Jaydip | #60, #61, #62 | 80 | _to fill_ | | _to fill_ | Heaviest load of the plan; Sumit paired on the ledger |
| Sagar | #42, #43, #44 | 75 | _to fill_ | | _to fill_ | |
| Sumit | #33, #34, #112 | 55 | _to fill_ | | _to fill_ | #112 late |
| Harshal | #52 | 20 | _to fill_ | | _to fill_ | Spare time used for #53 features (Plan 3) |
| Naitik | #23 | 10 | _to fill_ | | _to fill_ | |
| Gaurang | – (pull-forward) | 0 | _to fill_ | | _to fill_ | Frontend rebuild 2026-10-06 |
| Jay | – (pull-forward) | 0 | _to fill_ | | _to fill_ | #83/#84 started |
| Ayush | – (support) | 0 | _to fill_ | | _to fill_ | Shared breaker, load host |
| **Total** | | **240** | | | | |

Flag any member more than 25 % over or under their estimate in the Sunday sync, and rebalance Plan 5–6 tickets.

## 5. Risks carried into Plan 5

| Risk | Impact | Action | Owner |
|---|---|---|---|
| Stack never run with Plans 2–4 together | Demo segments 1–3 fail live on Oct 12 | Full `docker compose up` + seed + one settlement **on Sat Oct 10 / Sun Oct 11**; fix forward | Ayush, Sumit |
| Plan 4 not committed | Nothing reviewable or recoverable; per-member attribution unclear | Make the `commits/commit-plan-04.md` commits on `plan_4` before the demo | Each member, Sumit coordinates |
| Fraud scorer (#55) not built | Demo segment 4 ("flags a seeded shill pattern") can't be shown as an alert | Show the consumer and the features on the replayed dataset instead, and say so | Harshal |
| 1000 bids/s not demonstrated | Plan 7 target at risk | Host run per `docs/perf/week-09-baseline.md` §6; ≥ 2 bid workers | Naitik, Ayush |
| Razorpay test mode untested live | Settlement demo depends on the mock | Demo with the mock adapter; show test mode only if a rehearsal passes | Jaydip |

## 6. Mid-semester demo (Mon Oct 12)

Script: `docs/demo/mid-semester-script.md`. **Proposed rehearsal owner: Sumit** (runs both rehearsals and the timer),
with **Ayush** owning the stack on the demo machine. To be confirmed at the Sunday sync; the plan's Thursday and
Friday rehearsals (Oct 8, 9) didn't happen because the code wasn't frozen.
