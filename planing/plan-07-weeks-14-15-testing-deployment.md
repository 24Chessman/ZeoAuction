# Plan 7 — Testing & Deployment

| | |
|---|---|
| **Weeks** | 14–15 |
| **Dates** | Mon Nov 2 – Fri Nov 13, 2026 |
| **Jira sprint** | sprint-7 |
| **Milestone** | #109 *Testing and Deployment complete* (owner: Ayush) |
| **Proposal phase** | Testing & Deployment — end-to-end suite, ledger reconciliation, load testing, Render and Vercel deployment, monitoring dashboards |

## Goal

No new features. By Nov 13 we **prove** the system against every success metric in the proposal (§10)
and **run it live**:
- Every test rig in SDD Table 9.4 exists and runs: contract, end-to-end, concurrency, load/soak, fraud metric,
  reconciliation, browser end-to-end and chaos tests.
- All services are deployed on Render from the Render blueprint, the SPA is on Vercel, and the Prometheus, Grafana and Jaeger
  dashboards are live.
- The architecture decision records and design documents are written, each with its measured results.

## Work breakdown (Jira)

| Jira | Task | Owner | Epic | Hours | Due |
|---|---|---|---|---|---|
| #98 | Deploy all services via Render blueprint with managed Postgres and Key Value | Ayush | Infrastructure | 15 | Nov 13 |
| #99 | Deploy React SPA to Vercel with preview deployment per PR | Ayush | Infrastructure | 8 | Nov 13 |
| #100 | Build Prometheus and Grafana dashboards | Ayush | Infrastructure | 10 | Nov 13 |
| #101 | Instrument distributed tracing with Jaeger | Ayush | Infrastructure | 7 | Nov 13 |
| #102 | Build load and soak test rig: 1000 bids/s, 500 watchers | Ayush | Testing | 10 | Nov 13 |
| #26 | Write contract tests: bid service → orchestrator | Naitik | Testing | 15 | Nov 13 |
| #48 | Write contract tests for KYC gate and pricing engine | Sagar | Testing | 15 | Nov 13 |
| #36 | Build end-to-end auction lifecycle scenario suite | Sumit | Testing | 20 | Nov 13 |
| #67 | Run 1000-settlement reconciliation test | Jaydip | Testing | 10 | Nov 13 |
| #57 | Build fraud metric evaluation harness | Harshal | Testing | 15 | Nov 13 |
| #76 | Write frontend end-to-end tests | Gaurang | Testing | 15 | Nov 13 |
| #86 | Write end-to-end tests for admin and adjudication flows | Jay | Testing | 10 | Nov 13 |
| #85 | Complete responsive layout and accessibility pass | Jay | Frontend | 20 | Nov 13 |
| #27 | Author ADR: bid pipeline and deterministic conflict resolution | Naitik | Documentation | 15 | Nov 13 |
| #37 | Document settlement state machine and publish ADR | Sumit | Documentation | 15 | Nov 13 |
| #49 | Author ADR: KYC data retention and lawful basis, plus pricing docs | Sagar | Documentation | 15 | Nov 13 |
| #58 | Write fraud detection design document and measured results | Harshal | Documentation | 15 | Nov 13 |
| #68 | Author settlement policy and escrow-simulation ADR | Jaydip | Documentation | 10 | Nov 13 |
| #109 | **Milestone: Testing and Deployment complete** | Ayush | Milestones | – | Nov 13 |

## What we will do

### Week 14 — Deploy early, then test on it
**Deployment first (Ayush)**, so that the hosted environment is tested for two weeks and not two days:
- **Render (#98)**: a `render.yaml` blueprint declaring every service, disk, environment group and the cron entry. Use managed
  PostgreSQL (one instance, **a schema and credential per service** enforced by GRANTs) and managed Key-Value.
  Kafka runs as the private service provisioned in Plan 1. **Use the paid tier through the final demo** so services don't spin down.
  Images promoted to Render are the images CI built (environment parity).
- **Vercel (#99)**: a static SPA build with a preview deployment per PR.
- **CI stages**: fill in the contract-test and end-to-end stages that were stubbed in Plan 2, and add deploy hooks on merge to `main`.
- **Observability (#100, #101)**: Grafana dashboards for bid throughput, latency histograms and escrow-sweep health, driven by the
  SDD Table 9.2 metrics (`bids_accepted_total`, `bid_ack_latency_seconds`, `ws_fanout_latency_seconds`,
  `escrow_sweep_lag_seconds`, `ledger_reconciliation_failures`, `fraud_alerts_before_close_ratio`,
  `circuit_breaker_state`). Jaeger traces span a full settlement path across services.

### Test rigs (everyone), each mapped to a success metric

| Rig | Owner | Proves | Pass criterion |
|---|---|---|---|
| Contract CT-1 Bid → Orchestration (#26) | Naitik | NFR-MAINT-3 | CI fails if either side changes the state shape |
| Contract CT-2 KYC gate, CT-3 Pricing (#48) | Sagar | FR-TEST-1 | Status vocabulary, refusal code and money type pinned |
| End-to-end lifecycle suite (#36) | Sumit | FR-TEST-2 | KYC-gated listing → bid → settle → hold → release, in CI on Compose; includes the **time-accelerated fixture** covering every terminal path |
| Reconciliation, 1000 settlements (#67) | Jaydip | AC-08 | captured = bid + fee; payout = captured − fee; never both released and refunded; **zero failures** |
| Fraud metric harness (#57) | Harshal | AC-14 | recall ≥ 0.90 at precision ≥ 0.75; late alerts count as misses |
| Load and soak rig (#102) | Ayush + Naitik | AC-01/03/05 | 1000 bids/s over 50 auctions for 10 min, ≤0.1% errors; 200 bids/s on one auction; ack p95 < 500 ms; fan-out p95 < 100 ms with 500 watchers. **Run on the dedicated 8 vCPU / 16 GB host only** |
| Frontend end-to-end (#76) | Gaurang | FR-TEST-7 | Bid, KYC and dispute journeys in a real browser |
| Admin/adjudication end-to-end (#86) | Jay | FR-TEST-7 | KYC approval, suspension, both dispute outcomes |
| **Chaos tests** (unticketed) | Each service owner | AC-13 | Stop each service → the rest keeps serving → it recovers unaided via restart policy and health check; one documented test per service |
| KYC gate API test | Sagar | AC-06 | Zero auctions created by non-VERIFIED tokens |

### Frontend finish — Jay (#85)
- Three responsive breakpoints. On mobile, a **sticky bid bar** (SDD Fig. 8.10).
- Accessibility pass: keyboard navigation, focus order, 4.5:1 contrast, labels, and screen-reader announcement of price changes.

### Week 15 — Fix, tune, and document
- Fix what the rigs found. Tune against the load results. If a target is still missed, **report the measured curve
  and the bottleneck** rather than dropping the target (proposal risk table).
- **Documentation** (each owner writes their own):
  - #27 ADR bid pipeline and conflict resolution (Naitik)
  - #37 settlement state machine and ADR, with the time-accelerated fixture results attached (Sumit)
  - #49 KYC retention and lawful basis ADR and pricing docs (Sagar)
  - #58 fraud design doc and the **measured** curve (Harshal)
  - #68 settlement policy and escrow-simulation ADR: states plainly that the platform never touches real money (Jaydip)
- Generate and publish the final OpenAPI spec (FR-DOC-1).

## Definition of done / integration gate (#109)
- [ ] Every service is live on Render from the Render blueprint, the SPA is live on Vercel, and PR previews work
- [ ] CI runs lint → unit (80%) → contract → end-to-end → image build, and deploys on merge
- [ ] Grafana dashboards and Jaeger traces are live on the hosted deployment
- [ ] The end-to-end suite is green, including every escrow terminal path under time acceleration
- [ ] The 1000-settlement reconciliation has zero failures
- [ ] The load/soak report is done on the dedicated host, with measured numbers against every performance target
- [ ] The fraud harness report shows recall and precision against target
- [ ] A chaos test is documented for every service
- [ ] Frontend and admin browser end-to-end tests are green; the accessibility pass is done
- [ ] All the ADRs and design documents listed above are merged

## Risks this window
| Risk | Mitigation |
|---|---|
| Hosted deployment behaves differently from Compose | Deploy in week 14 (not 15); config differences are confined to connection strings in environment groups |
| Load targets missed | Known since the Plan 4 baseline; report the curve and bottleneck honestly |
| Test failures reveal feature bugs late | Fix-only rule; each owner triages their own failures within 24 h |
