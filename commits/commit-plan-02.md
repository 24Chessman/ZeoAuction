# Commit plan — Plan 2: Bid Service MVP (weeks 3–5, Aug 17 – Sep 4)

**Status: projected.** The paths follow the Plan 1 layout. Update this file to match what actually lands.
**Milestone:** #104 *Bid Service MVP integrated*. Naitik tags `plan-02`. **Checkpoint:** #111 week-5 audit (Sumit).

Layout used inside every service from here on:
- `app/api.py`: routes
- `app/domain/`: pure logic, no I/O
- `app/adapters/`: Redis, Kafka, PostgreSQL, HTTP clients
- `app/settings.py`: settings
- `tests/`: tests

The frontend lives in `frontend/src/{components/ui,features/<feature>,lib}`.

## Summary by member

| Member | Jira this plan | Commits | Focus |
|---|---|---|---|
| Naitik | #19, #20 (65 h) | 5 | Validation, sequencing, conflict resolution, bid endpoints, replay determinism |
| Sumit | #29, #30, #31, #111 (55 h) | 6 | CT-1 provider, Kafka producer, Redis buffer, flusher, idempotency, week-5 note |
| Ayush | #90, #91 (30 h) | 4 | Shared DB/Redis helpers, auth endpoints, JWT rotation, CI gates |
| Jay | #78, #79 (45 h) | 3 | Design tokens, component library, auth screens |
| Harshal | #51 (18 h) | 3 | Labelled synthetic dataset, 500 auctions / 200 rings |
| Gaurang | pull-forward | 3 | Frontend scaffold, bid screen against mocks, WebSocket client spike |
| Jaydip | pull-forward | 1 | `PaymentPort` + `MockPaymentAdapter` early (#59) |
| Sagar | pull-forward | 1 | KYC design notes ahead of Plan 3 |

## Commits in merge order

### Week 3 — foundations for the hot path

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 1 | Ayush | `ayush/support-common-db` | `feat(common): settings, PostgreSQL and Redis helpers with readiness checks` | `libs/zeo-common/zeo_common/{settings,db,redis}.py`, `libs/zeo-common/tests/test_db_redis.py`, `libs/zeo-common/pyproject.toml` | support |
| 2 | Gaurang | `gaurang/frontend-scaffold` | `feat(frontend): scaffold React 18 + Vite + Tailwind app shell and API client` | `frontend/` (package.json, vite config, `src/main.tsx`, `src/lib/api/`) | pull-forward |
| 3 | Sumit | `sumit/ct1-provider` | `feat(orchestrator): auction CRUD and GET /auctions/{id}/state (CT-1 provider)` | `services/auction-orchestrator/app/{api,settings}.py`, `app/domain/auction.py`, `app/adapters/auction_repo.py`, `tests/test_auction_api.py` | support (CT-1) |
| 4 | Naitik | `naitik/19-contract-clients` | `feat(bid): circuit-broken clients for CT-1 and CT-3 with contract fakes` | `services/bid/app/adapters/{auction_client,pricing_client}.py`, `tests/fakes.py`, `tests/test_clients.py` | #19 |
| 5 | Sumit | `sumit/29-kafka-producer` | `feat(bid): BidAccepted v1 producer on bid.events keyed by auction_id` | `services/bid/app/adapters/kafka_producer.py`, `tests/test_kafka_producer.py` | #29 |
| 6 | Ayush | `ayush/auth-endpoints` | `feat(auth): registration, login, logout and /users/me` | `services/auth-user/app/{api,settings}.py`, `app/domain/users.py`, `app/adapters/user_repo.py`, `app/security/passwords.py`, `tests/test_users_api.py` | support |
| 7 | Jay | `jay/78-design-tokens` | `feat(frontend): design tokens with contrast-checked palette` | `frontend/src/design/tokens.ts`, `frontend/tailwind.config.ts` | #78 |
| 8 | Harshal | `harshal/51-dataset-generator` | `feat(fraud): labelled synthetic auction and shill-ring generator` | `services/fraud-detector/dataset/{generator,patterns}.py`, `services/fraud-detector/tests/test_generator.py` | #51 |

### Week 4 — the hot path (#19 due Aug 28, #29 due Aug 28)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 9 | Naitik | `naitik/19-bid-validation` | `feat(bid): validate eligibility, funds, auction-open and increment before any state change` | `services/bid/app/domain/validation.py`, `services/bid/app/errors.py`, `tests/test_validation.py` | #19 |
| 10 | Sumit | `sumit/31-idempotency` | `feat(bid): idempotency guard with SETNX and unique idempotency key` | `services/bid/app/domain/idempotency.py`, `tests/test_idempotency.py` | #31 |
| 11 | Sumit | `sumit/30-price-buffer` | `feat(bid): Redis current-price buffer and bounded write batch` | `services/bid/app/adapters/price_buffer.py`, `tests/test_price_buffer.py` | #30 |
| 12 | Naitik | `naitik/20-conflict-resolution` | `feat(bid): server_seq allocation and compare-and-set conflict resolution` | `services/bid/app/domain/{sequencing,conflict}.py`, `tests/test_conflict_resolution.py` | #20 |
| 13 | Ayush | `ayush/91-jwt-rotation` | `feat(auth): JWT access tokens with rotating refresh tokens and reuse detection` | `services/auth-user/app/security/tokens.py`, `app/domain/refresh_tokens.py`, `libs/zeo-common/zeo_common/auth.py`, `tests/test_tokens.py` | #91 |
| 14 | Jay | `jay/78-component-library` | `feat(frontend): shared component library primitives` | `frontend/src/components/ui/*.tsx`, `frontend/src/components/ui/__tests__/` | #78 |
| 15 | Gaurang | `gaurang/69-bid-screen-mock` | `feat(frontend): auction detail and bid form against the mocked bid contract` | `frontend/src/features/bidding/`, `frontend/src/mocks/bids.ts` | pull-forward #69 |
| 16 | Jaydip | `jaydip/59-payment-port` | `feat(payment): PaymentPort interface and deterministic MockPaymentAdapter` | `services/payment-escrow/app/payment_port/{port,mock_adapter}.py`, `tests/test_mock_adapter.py` | pull-forward #59 |

### Week 5 — integration and the gate (everything due Sep 4)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 17 | Naitik | `naitik/19-bid-endpoints` | `feat(bid): POST and GET bid endpoints wiring the full hot path` | `services/bid/app/{api,settings}.py`, `tests/test_place_bid_api.py` | #19, #20 |
| 18 | Sumit | `sumit/30-flusher` | `feat(bid-flusher): batched persistence with Kafka replay recovery` | `services/bid-flusher/app/{flusher,replay}.py`, `services/bid-flusher/tests/test_flusher.py` | #30 |
| 19 | Naitik | `naitik/20-replay-determinism` | `test(bid): equal concurrent bids resolve identically across 100 replays` | `services/bid/tests/test_replay_determinism.py` | #20 |
| 20 | Ayush | `ayush/90-ci-gates` | `ci: enforce 80% coverage and build every service image per PR` | `.github/workflows/ci.yml` | #90 |
| 21 | Jay | `jay/79-auth-screens` | `feat(frontend): login, registration and profile screens` | `frontend/src/features/auth/` | #79 |
| 22 | Harshal | `harshal/51-dataset-fixture` | `test(fraud): seeded dataset v1, 500 auctions and 200 labelled rings` | `tests/fixtures/fraud/{dataset-v1.jsonl.gz,labels-v1.csv,README.md}` | #51 |
| 23 | Harshal | `harshal/51-dataset-replay` | `feat(fraud): replay the labelled dataset into bid.events` | `services/fraud-detector/dataset/replay.py`, `services/fraud-detector/tests/test_replay.py` | #51 |
| 24 | Gaurang | `gaurang/71-ws-spike` | `feat(frontend): WebSocket client spike against a mock server` | `frontend/src/lib/ws/`, `frontend/src/mocks/ws-server.ts` | pull-forward #71 |
| 25 | Sagar | `sagar/kyc-design` | `docs(kyc): endpoint and verification-flow design notes` | `services/kyc/docs/design.md` | pull-forward |
| 26 | Sumit | `sumit/111-week5-audit` | `docs(milestones): week-5 progress note and hours audit` | `docs/progress/week-05.md` | #111 |

**Cross-owner commits:** 5, 10 and 11 are Sumit's code inside Naitik's `bid` service, so Naitik must approve them.

## Gate (#104)

- [ ] `POST /api/v1/auctions/{id}/bids` returns 202 on the Compose stack; all 4 validation rules reject with taxonomy codes
- [ ] Replay determinism test passes (commit 19); an idempotent retry creates no second row
- [ ] Bids appear on `bid.events` keyed by `auction_id`; the flusher persists by size and age; crash recovery by replay is demonstrated
- [ ] Register → login → refresh → `/users/me` works; refresh-token reuse is detected
- [ ] CI blocks coverage below 80%; the dataset fixture reproduces 500 auctions / 200 rings from its seed
- [ ] Week-5 note published → tag `plan-02`
