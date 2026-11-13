# Commit plan — Plan 7: Testing & Deployment (weeks 14–15, Nov 2 – Nov 13)

**Status: projected.** **Milestone:** #109 *Testing and Deployment complete*. Ayush tags `plan-07`.
No new features. Only test rigs, deployment, observability, fixes and documentation.

## Summary by member

| Member | Jira this plan | Commits | Focus |
|---|---|---|---|
| Ayush | #98–#102 (50 h) | 6 | Render blueprint, Vercel, dashboards, tracing, load rig, CI stages |
| Sumit | #36, #37 (35 h) | 3 | End-to-end lifecycle suite, time-accelerated fixture, settlement ADR |
| Naitik | #26, #27 (30 h) | 3 | CT-1 contract test, ADR-0001/0002, load results write-up |
| Sagar | #48, #49 (30 h) | 3 | CT-2 and CT-3 contract tests, KYC retention ADR, pricing docs |
| Harshal | #57, #58 (30 h) | 2 | Fraud metric harness, fraud design doc with the measured curve |
| Jay | #85, #86 (30 h) | 2 | Responsive and accessibility pass, admin end-to-end tests |
| Jaydip | #67, #68 (20 h) | 2 | 1000-settlement reconciliation, escrow-simulation ADR |
| Gaurang | #76 (15 h) | 1 | Frontend browser end-to-end tests |
| Every owner | AC-13 | 1 each | Chaos test for each of their services |

## Commits in merge order

### Week 14 — deploy first, then build the rigs

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 1 | Ayush | `ayush/98-render-blueprint` | `build(render): blueprint for every service with managed Postgres and Key Value` | `render.yaml`, `docs/deploy/render.md` | #98 |
| 2 | Ayush | `ayush/99-vercel` | `build(frontend): Vercel deployment with preview per pull request` | `frontend/vercel.json`, `docs/deploy/vercel.md` | #99 |
| 3 | Ayush | `ayush/ci-contract-e2e-stages` | `ci: contract and end-to-end stages on the Compose stack, deploy on merge` | `.github/workflows/{ci,deploy}.yml` | #98 |
| 4 | Ayush | `ayush/100-dashboards` | `feat(observability): Prometheus scrape config and Grafana dashboards` | `infra/observability/{prometheus.yml,grafana/}`, `docker-compose.yml` | #100 |
| 5 | Ayush | `ayush/101-tracing` | `feat(observability): Jaeger tracing across settlement paths` | `libs/zeo-common/zeo_common/tracing.py`, `infra/observability/jaeger/` | #101 |
| 6 | Naitik | `naitik/26-ct1-contract-test` | `test(contracts): consumer-driven CT-1 test between bid and orchestrator` | `tests/contract_ct/test_ct1_auction_state.py` | #26 |
| 7 | Sagar | `sagar/48-ct2-ct3-tests` | `test(contracts): CT-2 listing gate and CT-3 pricing contract tests` | `tests/contract_ct/test_ct2_kyc_gate.py`, `tests/contract_ct/test_ct3_pricing.py` | #48 |
| 8 | Sumit | `sumit/36-e2e-suite` | `test(e2e): KYC-gated listing through bid, settle, hold and release on Compose` | `tests/e2e/test_auction_lifecycle.py`, `tests/e2e/conftest.py` | #36 |
| 9 | Sumit | `sumit/36-time-fixture` | `test(e2e): time-accelerated fixture covering every escrow terminal path` | `tests/e2e/test_escrow_terminal_paths.py`, `tests/e2e/clock.py` | #36 |
| 10 | Jaydip | `jaydip/67-reconciliation-1000` | `test(payment): 1000 simulated settlements reconcile exactly` | `tests/e2e/test_reconciliation_1000.py` | #67 |
| 11 | Harshal | `harshal/57-metric-harness` | `test(fraud): evaluation harness, recall at fixed precision, late alerts count as misses` | `services/fraud-detector/eval/harness.py`, `tests/fraud/test_metric_harness.py` | #57 |
| 12 | Ayush | `ayush/102-load-rig` | `test(load): 1000 bids/s and 500 watchers soak rig for the dedicated host` | `tests/load/{soak_rig.py,watchers.py,README.md}` | #102 |
| 13 | Gaurang | `gaurang/76-frontend-e2e` | `test(frontend): browser end-to-end tests for the bid, KYC and dispute journeys` | `frontend/e2e/`, `frontend/playwright.config.ts` | #76 |
| 14 | Jay | `jay/86-admin-e2e` | `test(frontend): end-to-end tests for KYC approval, suspension and both dispute outcomes` | `frontend/e2e/admin/` | #86 |

### Chaos tests (AC-13) — one commit per service owner, during week 14

| # | Member | Commit message | Files |
|---|---|---|---|
| 15 | Naitik | `test(chaos): stop bid and escrow-sweep, the rest keeps serving and recovers` | `tests/chaos/test_bid.py`, `tests/chaos/test_escrow_sweep.py` |
| 16 | Sumit | `test(chaos): stop auction-orchestrator and bid-flusher` | `tests/chaos/test_orchestrator.py`, `tests/chaos/test_flusher.py` |
| 17 | Sagar | `test(chaos): stop kyc, pricing and search-analytics` | `tests/chaos/test_kyc.py`, `test_pricing.py`, `test_search.py` |
| 18 | Harshal | `test(chaos): stop fraud-detector, bidding unaffected and backlog replayed` | `tests/chaos/test_fraud_detector.py` |
| 19 | Jaydip | `test(chaos): stop payment-escrow, orders parked and settled on return` | `tests/chaos/test_payment.py` |
| 20 | Jay | `test(chaos): stop dispute and admin-moderation` | `tests/chaos/test_dispute.py`, `tests/chaos/test_admin.py` |
| 21 | Ayush | `test(chaos): stop auth-user and ws-gateway, clients fall back to refresh` | `tests/chaos/test_auth.py`, `tests/chaos/test_ws_gateway.py`, `tests/chaos/conftest.py` |

Commit 21 includes the shared `conftest.py`, so Ayush merges it first among 15–21.

### Week 15 — fix, tune, document

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 22 | Jay | `jay/85-responsive-a11y` | `feat(frontend): responsive breakpoints, sticky mobile bid bar, accessibility pass` | `frontend/src/` (layout + components), `docs/accessibility.md` | #85 |
| 23 | Naitik | `naitik/27-adr-bid-pipeline` | `docs(adr): ADR-0001/0002 bid pipeline and deterministic conflict resolution` | `docs/adr/0001-server-seq-ordering.md`, `docs/adr/0002-redis-cas-batched-persistence.md`, `docs/perf/final-load-results.md` | #27 |
| 24 | Sumit | `sumit/37-settlement-adr` | `docs(adr): settlement state machine ADR with time-accelerated fixture results` | `docs/adr/0006-escrow-sweep-cron.md`, `docs/state-machines.md` | #37 |
| 25 | Sagar | `sagar/49-kyc-retention-adr` | `docs(adr): KYC data retention and lawful basis, plus pricing docs` | `docs/adr/0005-kyc-status-jwt-claim.md`, `docs/adr/0013-kyc-retention.md`, `docs/pricing.md` | #49 |
| 26 | Harshal | `harshal/58-fraud-design-doc` | `docs(fraud): design document and measured recall/precision curve` | `docs/adr/0008-dataset-before-detector.md`, `docs/fraud/design-and-results.md` | #58 |
| 27 | Jaydip | `jaydip/68-escrow-adr` | `docs(adr): settlement policy and escrow-simulation statement` | `docs/adr/0003-saga-compensations.md`, `docs/adr/0004-append-only-ledger.md`, `docs/adr/0007-payment-port.md` | #68 |
| 28 | Ayush | `ayush/openapi-publish` | `docs(api): publish generated OpenAPI for every service` | `docs/api/*.json`, `scripts/export-openapi.sh` | FR-DOC-1 |

## Gate (#109)

- [ ] Live on Render and Vercel. CI runs lint → unit → contract → e2e → build and deploys on merge
- [ ] Grafana and Jaeger live. E2E, reconciliation (0 failures), fraud harness and load report all done
- [ ] Chaos test documented for all 13 services. Accessibility pass done. All ADRs merged → tag `plan-07`
