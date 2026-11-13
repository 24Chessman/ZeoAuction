# ZeoAuction — Implementation Plans

This folder breaks the 16-week ZeoAuction build into **two-week implementation plans**.
Nothing here is code; these are the plans we execute against.

**Sources** (all in `project_docs/`):

| Source | What it gave us |
|---|---|
| `zeoauction_jira_import (1).csv` | The timeline: 96 tasks, owners, hours, start/due dates, sprints, milestones |
| `main (2).tex` / `project (2).pdf` | Project proposal: scope, settlement policy, tech stack, roles, success metrics, risks |
| `system_design_ZA.pdf` | System Design Document (SDD) v1.0: architecture, data design, state machines, API contracts, UI mockups |
| `timelineChartZA/` + `timelineChartZA.pdf` | Gantt / Jira timeline, calendar and backlog screenshots |

---

## The plans

Each plan lines up with one Jira sprint and ends on that sprint's **integration milestone**, so every
plan finishes with something the whole team can demo.

| # | Plan | Weeks | Dates (2026) | Jira sprint | Ends with milestone |
|---|---|---|---|---|---|
| 1 | [Setup & Foundations](plan-01-weeks-01-02-setup.md) | 1–2 | Aug 3 – Aug 14 | sprint-1 | #103 Setup phase integrated |
| 2 | [Bid Service MVP](plan-02-weeks-03-05-bid-service-mvp.md) | 3–5 ⚠️ | Aug 17 – Sep 4 | sprint-2 | #104 Bid Service MVP integrated + week-5 audit |
| 3 | [Identity & Real-Time](plan-03-weeks-06-07-identity-realtime.md) | 6–7 | Sep 7 – Sep 18 | sprint-3 | #105 Identity and Real-Time integrated |
| 4 | [Pricing, Payments & Fees](plan-04-weeks-08-09-pricing-payments-fees.md) | 8–9 | Sep 21 – Oct 2 | sprint-4 | #106 Pricing, Payments and Fees integrated + week-9 audit |
| 5 | [Fraud Detection v1 & Mid-Semester Demo](plan-05-weeks-10-11-fraud-v1-mid-demo.md) | 10–11 | Oct 5 – Oct 16 | sprint-5 | #107 Fraud Detection v1 integrated · **Mid-Sem Demo Oct 12** |
| 6 | [Disputes, Search & Admin](plan-06-weeks-12-13-disputes-search-admin.md) | 12–13 | Oct 19 – Oct 30 | sprint-6 | #108 Disputes, Search and Admin integrated + week-13 audit |
| 7 | [Testing & Deployment](plan-07-weeks-14-15-testing-deployment.md) | 14–15 | Nov 2 – Nov 13 | sprint-7 | #109 Testing and Deployment complete |
| 8 | [Final Delivery](plan-08-week-16-final-delivery.md) | 16 ⚠️ | Nov 16 – Nov 20 | sprint-8 | #110 Final delivery · **Final Demo Nov 18** |

⚠️ **Two plans aren't exactly two weeks, on purpose.** In the Jira timeline, sprint 2 runs for three weeks (the Bid Service MVP milestone and the
week-5 hours audit both fall on Sep 4), and sprint 8 is only the final week. If we cut at strict 14-day
boundaries instead, six of the eight milestones would split across two plans. Every other plan is exactly
two weeks.

---

## Team and ownership

| Member | ID | Owns (interface owner) | Main workstreams |
|---|---|---|---|
| Naitik | 202512006 | Bid Processing, Integration Testing | Bid validation, conflict resolution, lifecycle guards, auto-release scheduler |
| Sumit | 202512124 | Auction Orchestration, Documentation, Milestones | State machine, Kafka producer, Redis buffer, settlement transitions, invoice |
| Sagar | 202512107 | KYC, Pricing Engine, Search | KYC service + listing gate, pricing engine, full-text search |
| Harshal | 202512013 | Fraud Detection | Event schema, synthetic dataset, streaming detector, ring clustering |
| Jaydip | 202512090 | Payment, Fees & Escrow | Payment port, provider adapter, fee engine, escrow ledger, saga, refunds |
| Gaurang | 202512007 | Frontend | Bidding UI, WebSocket client, KYC/dispute UI, notifications, seller dashboard |
| Jay | 202512123 | Dispute Management, Admin | Component library, auth screens, admin queues, adjudication console, audit log |
| Ayush | 202512084 | Auth, WebSocket Gateway, Infrastructure | Docker/Compose, Kafka, CI, JWT, gateway middleware, WS gateway, deployment, observability |

**Shared obligations for everyone, every plan:** review 2–3 PRs per week, keep unit-test coverage at 80% or higher on
your own code, attend the Tuesday 15-minute standup, and don't merge anything without **two approvals**.

---

## Planned hours per member per plan (from the Jira estimates)

| Member | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | Total |
|---|---|---|---|---|---|---|---|---|---|
| Naitik | 10 | 65 | 60 | 10 | – | 25 | 30 | – | 200 |
| Sumit | 20 | 55 | 20 | 55 | – | 15 | 35 | – | 200 |
| Sagar | – | – | 55 | 75 | 10 | 30 | 30 | – | 200 |
| Harshal | 12 | 18 | – | 20 | **70** | 50 | 30 | – | 200 |
| Jaydip | – | – | 20 | **80** | 30 | 50 | 20 | – | 200 |
| Gaurang | – | – | **100** | – | – | 70 | 15 | 15 | 200 |
| Jay | – | 45 | 20 | – | – | **95** | 30 | 10 | 200 |
| Ayush | 40 | 30 | 70 | – | – | 10 | 50 | – | 200 |

> **Planning risk: the load is uneven.** The proposal assumes a steady ~12.5 h/week per person, but the
> Jira dates bunch work together. The overloads (bold) are Gaurang with 100 h in weeks 6–7, Harshal with 70 h in
> week 10, Jay with 95 h in weeks 12–13, and Jaydip with 80 h in weeks 8–9. Each plan has a
> **"Pull-forward"** section that moves work from an overloaded window into an earlier one where that
> person has free time (for example, Gaurang builds UI against mocked contracts in Plan 2). The Jira due
> dates stay the same; only the start dates move earlier.

---

## Open decisions that must be closed in Plan 1

The documents disagree with each other in a few places. We need to settle each one in the first two weeks
and record it in an ADR:

1. **Payment provider: Razorpay or Stripe.** The proposal (§6, §7, §11) says *Razorpay test mode* (INR).
   The SDD (§5.2.1, `POST /webhooks/stripe`) and Jira tasks #60 and #64 say *Stripe test mode, manual capture*
   (USD in the examples). Either way the provider sits behind `PaymentPort`, alongside a `MockPaymentAdapter`.
   We need to pick one adapter and one currency.
2. **Third-party APIs.** The proposal lists Firebase Cloud Messaging and Cloudinary. The SDD says
   notifications go over the platform's own WebSocket ("no third-party push service is a dependency") and
   documents go to S3-compatible storage (SeaweedFS locally). We need to decide whether FCM and Cloudinary are
   in scope, for example Cloudinary for listing images only.
3. **Settlement policy numbers.** The flat fee amount, the currency, the protection-window length (default 7 days),
   the anti-snipe guard interval, and the extension cap. These become the `fee_config` row and must be fixed
   *before any settlement code is written* (SDD §1.3).
4. **SRS.** The SDD traces every design choice to requirement IDs in an SRS (FR-BID-3, AC-08, and so on), but the SRS isn't
   in `project_docs/`. We should add it so we can look those IDs up.

---

## Work in the design that has no Jira ticket

The SDD requires the items below, but no Jira task covers them. Each plan below assigns them to the
owner of the nearest workstream. They should be added to Jira as sub-tasks so the hours get tracked:

| Item | SDD reference | Slotted into |
|---|---|---|
| Repo layout, coding conventions, branch protection | §3.2 | Plan 1 |
| Architecture doc + per-service DB schemas + GRANT-based ownership | §4.1 | Plan 1 |
| Auction CRUD: `POST /auctions`, `publish`, `cancel`, `GET /auctions/{id}` | §7.2 | Plans 2–3 (Sumit) |
| User service endpoints: register, login, refresh, logout, `/users/me` | §7.2 | Plan 2 (Ayush) |
| `/healthz`, `/readyz`, `/metrics` on every service | §7.2, §9.2 | Plan 1 template, then every service |
| Circuit breakers on the 3 synchronous boundaries | §2.4, Table 2.2 | Plans 3–4 |
| Batched-persistence flusher + Kafka replay recovery | §4.4 | Plan 2 |
| Browse/search screen and seller "create auction" screen (frontend) | §8.2 | Plans 3 and 6 |
| `GET /notifications`, admin metrics, admin broadcasts | §7.2 | Plan 6 |
| Chaos test per service (stop it, confirm the rest serves, confirm it recovers) | §2.3.2, AC-13 | Plan 7 |
| Generated OpenAPI spec published per release | §7.1 | Plans 2 → 7 |

---

## Success metrics every plan builds towards (proposal §10)

- **Throughput:** 1000 bids/s aggregate across 50 auctions for 10 minutes (≤0.1% errors), and 200 bids/s on a single auction.
- **Latency:** bid acknowledgement p95 < 500 ms, and WebSocket fan-out p95 < 100 ms with 500 watchers.
- **Settlement:** 1000 settlements reconcile exactly, and no order is ever both released and refunded (zero tolerance).
- **Escrow:** nothing is released early, disputes on a closed window are rejected, and the sweep releases within 5 minutes of expiry.
- **KYC gate:** zero auctions are created by unverified accounts, tested at the API.
- **Resilience:** any one service can be stopped while the rest keep serving, and it restarts without anyone stepping in.
- **Fraud:** recall ≥ 0.90 at precision ≥ 0.75 on 500 auctions / 200 rings, with alerts raised before close.
- **Quality:** 80% coverage, 0 lint errors, 2 approvals per merge. **Effort:** 200 h per member.
