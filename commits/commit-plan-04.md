# Commit plan — Plan 4: Pricing, Payments & Fees (weeks 8–9, Sep 21 – Oct 2)

**Status: every row implemented in the working tree (2026-10-10), with Razorpay per ADR-0009, except commit 17 (conflict tuning), which is deferred: the week-9 baseline gave no evidence for a change (`docs/perf/week-09-baseline.md` §5). Not yet committed. File lists below are the actual files.** **Milestone:** #106 *Pricing, Payments and Fees integrated*. Jaydip tags `plan-04`.
**Checkpoint:** #112 week-9 audit (Sumit). ADR-0009 (Razorpay, INR) and ADR-0011 (₹99 fee) were accepted on 2026-10-10 and ride in commit 0.

## Summary by member

| Member | Jira this plan | Commits | Focus |
|---|---|---|---|
| Jaydip | #60, #61, #62 (80 h) | 4 | Fee engine + quote, escrow ledger, provider adapter, Orchestration → Payment breaker |
| Sagar | #42, #43, #44 (75 h) | 4 | Velocity, dynamic increment (CT-3 provider), hot-auction flag, CT-3 breaker |
| Sumit | #33, #34, #112 (55 h) | 4 | Invoice, settlement transition, SettlementStep events, week-9 note |
| Harshal | #52 (20 h) | 2 | Streaming consumer scaffold, dataset replay through Kafka |
| Naitik | #23 (10 h) | 2 | Load baseline report, conflict-resolution tuning |
| Gaurang | pull-forward | 2 | Real fee quote wired in, browse/search screen (unticketed) |
| Jay | pull-forward | 1 | Audit-log writer and dispute lifecycle spec ahead of Plan 6 |
| Ayush | none | 1 | Load-test host setup to support Naitik's baseline |

## Commits in merge order

### Week 8

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 0 | Jaydip | `jaydip/adr-0009-razorpay` | `docs(adr): accept Razorpay test mode and the INR fee (ADR-0009, ADR-0011)` | `docs/adr/0009-payment-provider.md`, `docs/adr/0011-settlement-policy.md`, `docs/adr/README.md`, `config/settlement-policy.yaml`, `infra/postgres/init/61-payment-razorpay.sql`, `tests/contracts/test_settlement_policy.py`, `contracts/events/examples/*.json`, `contracts/openapi/common.v1.yaml`, `infra/postgres/seed/dev-seed.sql`, `.env.example` | #60 |
| 0b | Ayush | `ayush/shared-breaker` | `refactor(common): move the circuit breaker into zeo_common for CT-4 and capture` | `libs/zeo-common/zeo_common/circuit_breaker.py`, `libs/zeo-common/tests/test_circuit_breaker.py`, `services/bid/app/adapters/circuit_breaker.py` | support #33 |
| 1 | Jaydip | `jaydip/61-fee-engine` | `feat(payment): flat-fee engine and GET /fees/quote from the active fee_config` | `services/payment-escrow/app/domain/fees.py` (replaces `app/fees.py`), `tests/test_fee_quote.py`, `contracts/openapi/payment.v1.yaml`, `contracts/errors/payment-error-codes.yaml`, `tests/test_error_codes.py` | #61 |
| 2 | Jaydip | `jaydip/62-escrow-ledger` | `feat(payment): append-only escrow ledger writer with sign and invariant checks` | `services/payment-escrow/app/domain/{ledger,orders}.py`, `app/adapters/repository.py`, `tests/{test_ledger,test_orders,test_postgres_repo}.py` | #62 |
| 3 | Sagar | `sagar/42-velocity` | `feat(pricing): rolling bid-velocity tracking from bid.events` | `services/pricing/app/domain/{__init__,velocity}.py`, `app/adapters/{__init__,bid_consumer,repository}.py`, `app/settings.py`, `requirements.txt`, `tests/{support,test_velocity,test_bid_consumer,test_postgres_repo}.py` | #42 |
| 4 | Sagar | `sagar/43-dynamic-increment` | `feat(pricing): dynamic minimum increment served on CT-3 and cached in Redis` | `infra/postgres/init/51-pricing-dynamic.sql`, `services/pricing/app/domain/increment.py`, `app/{api,service,main}.py`, `tests/{test_increment,test_service,test_api}.py`, `README.md`, `docker-compose.yml` (pricing env) | #43 |
| 5 | Sumit | `sumit/34-invoice` | `feat(payment): invoice generation, winning bid plus flat fee, never for losing bidders` | `services/payment-escrow/app/domain/invoice.py`, `tests/test_invoice.py` | #34 |
| 6 | Harshal | `harshal/52-consumer-scaffold` | `feat(fraud): streaming consumer with per-auction sliding windows and offset management` | `services/fraud-detector/app/{consumer,windows,settings,main}.py`, `requirements.txt`, `tests/{kafka_fakes,test_consumer}.py`, `README.md`, `docker-compose.yml` (fraud env) | #52 |
| 7 | Gaurang | `gaurang/70-real-fee-quote` | `feat(frontend): INR money, Razorpay Checkout and the winner's Pay now panel` | `frontend/src/lib/{money,money.test,policy,errors}.ts`, `frontend/src/lib/api/{index,types}.ts`, `frontend/src/lib/payments/razorpay{,.test}.ts`, `frontend/src/lib/mock/{seed,server,orders.test}.ts`, `frontend/src/components/auction/{SettlementPanel,BidPanel}.tsx`, `frontend/src/pages/{AuctionDetailPage,seller/CreateAuctionPage}.tsx` | #70 follow-up |
| 8 | Ayush | `ayush/102-loadtest-host` | `build(loadtest): provisioning script for the dedicated 8 vCPU / 16 GB host` | `infra/loadtest/{provision.sh,seed-auctions.sql,README.md}`, `.gitignore` | support #23 |

### Week 9

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 9 | Jaydip | `jaydip/60-provider-adapter` | `feat(payment): Razorpay test-mode adapter with Checkout and manual capture (ADR-0009)` | `services/payment-escrow/app/payment_port/{port,mock_adapter,razorpay_adapter}.py`, `tests/{test_mock_adapter,test_razorpay_adapter}.py`, `app/settings.py`, `requirements.txt` | #60 |
| 10 | Sumit | `sumit/33-settlement-transition` | `feat(payment): settlement S1–S3 — order, Checkout, capture, escrow hold` | `services/payment-escrow/app/{service,api,main,worker}.py`, `tests/{support,conftest,test_settlement_flow}.py`, `contracts/openapi/internal/settlement.v1.yaml`, `services/payment-escrow/README.md`, `docker-compose.yml` | #33 |
| 11 | Jaydip | `jaydip/33-capture-breaker` | `feat(orchestrator): CT-4 to Payment behind the breaker; A7 settle on HELD` | `infra/postgres/init/32-auction-settlement.sql`, `services/auction-orchestrator/app/domain/{auction,anti_snipe,settlement}.py`, `app/adapters/{auction_repo,bid_events,payment_client,payment_events}.py`, `app/{service,settings,main,api}.py`, `tests/{test_settlement,test_postgres_repo}.py`, `requirements.txt`, `README.md` | #33 |
| 12 | Sumit | `sumit/33-settlement-events` | `feat(payment): publish SettlementStep v1 on payment.events` | `services/payment-escrow/app/adapters/kafka_producer.py`, `tests/test_settlement_events.py` | #33 |
| 13 | Sagar | `sagar/44-hot-auction` | `feat(pricing): hot-auction flagging with thresholds` | `services/pricing/app/domain/hot_auction.py`, `tests/test_hot_auction.py`. Commits 3, 4 and 13 import each other's modules (`service.py`, `repository.py`), so open them as one stacked PR and merge together | #44 |
| 14 | Sagar | `sagar/43-ct3-breaker` | `feat(bid): CT-3 breaker falls back to cached increment and flags increment_stale` | `services/bid/app/adapters/pricing_client.py` (fallback floored at the tier, 60 s TTL), `app/settings.py`, `tests/test_ct3_breaker.py`, `docker-compose.yml` (`PRICING_MODE=http`) | #43 |
| 15 | Harshal | `harshal/52-replay-proof` | `test(fraud): consumer replays dataset v1 in order and resumes after restart` | `services/fraud-detector/tests/test_replay_resume.py` | #52 |
| 16 | Naitik | `naitik/23-load-baseline` | `docs(perf): week-9 load baseline, p95 per segment against the 500 ms budget` | `docs/perf/week-09-baseline.md`, `tests/load/{aggregate_rig.py,README.md}`, `services/bid/tests/test_aggregate_rig.py` | #23 |
| 17 | Naitik | `naitik/23-tuning` | `perf(bid): tune conflict resolution against the week-9 baseline` | **Deferred** to after the host run; candidates in `docs/perf/week-09-baseline.md` §5 | #23 |
| 18 | Gaurang | `gaurang/browse-search-ui` | `feat(frontend): fee-on-win notice on the browse and search screen` | `frontend/src/pages/AuctionsPage.tsx` (the screen itself shipped in the 2026-10-06 rebuild) | unticketed |
| 19 | Jay | `jay/83-audit-writer` | `feat(admin): audit-log writer library and dispute lifecycle draft` | `libs/zeo-common/zeo_common/audit.py`, `libs/zeo-common/tests/test_audit.py`, `docs/dispute-lifecycle.md` | pull-forward #83, #84 |
| 20 | Sumit | `sumit/112-week9-audit` | `docs(milestones): week-9 progress note, hours audit and demo script` | `docs/progress/week-09.md`, `docs/demo/mid-semester-script.md`, `CLAUDE.md`, this file, `planing/plan-04-*.md` | #112 |

**Docs touched by commits 10 and 11:** `docs/state-machines.md` §1–2 (O1a authorize, A7 driven by Payment), `docs/architecture.md`
(CT-4), `contracts/README.md`.

**Cross-owner commits:**
- 5 and 12 are Sumit's code in Jaydip's service, so Jaydip approves.
- 11 is Jaydip's code in Sumit's service, so Sumit approves.
- 14 is Sagar's code in Naitik's service, so Naitik approves.

## Gate (#106)

- [ ] Close → invoice (bid + fee) → capture (mock and provider test mode) → CAPTURE, HOLD and FEE_RETAIN rows → IN_ESCROW. Losers not invoiced
- [ ] The quoted fee equals the invoiced fee (same `fee_version`). The ledger refuses UPDATE and a second terminal row
- [ ] Payment down → `AWAITING_CAPTURE_RETRY` → recovers. Pricing down → stale-increment fallback
- [ ] Baseline report published. Fraud consumer replays in order and survives a restart
- [ ] Week-9 note and demo script published → tag `plan-04`
