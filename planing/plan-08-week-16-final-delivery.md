# Plan 8 — Final Delivery

| | |
|---|---|
| **Weeks** | 16 (a single week; the last week of the project window) |
| **Dates** | Mon Nov 16 – Fri Nov 20, 2026 |
| **Jira sprint** | sprint-8 |
| **Milestone** | #110 *Final delivery complete* (owner: Sumit) |
| **Key event** | **Final Demo — Wed Nov 18** |
| **Proposal phase** | Final Demo — live deployment on Render and Vercel, measured performance results, final presentation |

## Goal

Deliver the finished platform: a **live demo on the hosted deployment**, a presentation of **measured
results against every success metric**, and the user-facing documentation. Nothing new gets built this
week; the only code changes allowed are critical fixes on a release branch.

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #77 | Write user manual and help guide with UI walkthrough | Gaurang | Documentation | 15 | Nov 18 |
| #87 | Write dispute policy and admin operations guide | Jay | Documentation | 10 | Nov 18 |
| #110 | **Milestone: Final delivery complete** | Sumit | Milestones | – | Nov 18 |

Everyone else has already used their Jira hours by this point. Their work this week is the
presentation, the rehearsal, and standing by to fix anything critical.

## What we will do

### Mon Nov 16 — Freeze and release
- Tag `v1.0.0` from `main`, deploy that exact tag to Render and Vercel, and freeze. After that, only critical fixes go in, each with two approvals.
- Confirm the paid Render tier is active and that the escrow-sweep cron is running (check `escrow_sweep_lag_seconds`).
- Load the demo seed data on the hosted deployment.

### Mon–Tue — Documentation (course deliverables)
- **User manual (#77, Gaurang)**: a UI walkthrough of every screen (browse, bid, KYC, seller dashboard, dispute,
  notifications). It must **state that the escrow flow is a functional simulation** and that no real money is involved.
- **Dispute policy and admin ops guide (#87, Jay)**: the protection window, evidence rules, adjudication outcomes, fee
  treatment by fault, and KYC review and suspension procedures.
- **Final results document (Sumit, with every owner contributing)**: a table of each proposal §10 metric with
  its target, the measured value, pass or miss, and evidence links (Grafana screenshots, harness reports,
  reconciliation output, chaos test notes). **Misses are reported with the curve and the bottleneck, not hidden.**
- Check the generated OpenAPI spec, the ADR index, and the README (how to run it locally in one command).

### Tue Nov 17 — Rehearsal
- Two full timed run-throughs on the **hosted** deployment.
- Suggested demo flow (each member presents their component):
  1. Architecture overview: services, Kafka topics, data ownership (Sumit)
  2. Registration and KYC → admin approval → gated listing, with the unverified seller refused (Sagar, Jay)
  3. Live bidding with two watchers: WebSocket price push, outbid alert, fee disclosure, anti-snipe (Gaurang, Ayush, Naitik)
  4. Close → invoice → capture → escrow hold in the ledger (Sumit, Jaydip)
  5. Dispute in the window → adjudication → refund with fee by fault; sweep auto-release (Jay, Jaydip, Naitik)
  6. Fraud detector flags a shill ring → auto-dispute with bid trace (Harshal)
  7. Resilience: stop a service live and show the rest still serves and it recovers (Ayush)
  8. Measured results: load, latency, reconciliation, fraud recall and precision; Grafana and Jaeger (Ayush, Harshal, Jaydip)
- Fallbacks: the local Compose stack on a laptop, plus a recorded video of the full flow.

### Wed Nov 18 — Final Demo
- Deliver the live demo and presentation. Submit the documents.

### Thu–Fri Nov 19–20 — Close-out
- **Purge all KYC sample documents** from object storage, as committed in the KYC retention ADR (proposal risk table).
- Final hours log: every member should total 200 h, and the team 1600 h.
- A short retrospective: what went well, what to change.
- Archive the Jira board. Decide whether to scale down the paid Render instances.

## Definition of done (#110)
- [ ] `v1.0.0` is tagged and running live on Render + Vercel
- [ ] The final demo is delivered on Nov 18
- [ ] The final results document covers every §10 metric with measured values and evidence
- [ ] The user manual (including the simulation statement) and the admin/dispute guide are submitted
- [ ] The OpenAPI spec, ADRs and README are final
- [ ] KYC sample documents are purged
- [ ] Final hours are logged (200 h per member)
