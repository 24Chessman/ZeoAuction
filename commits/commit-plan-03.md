# Commit plan — Plan 3: Identity & Real-Time (weeks 6–7, Sep 7 – Sep 18)

**Status: projected.** **Milestone:** #105 *Identity and Real-Time integrated*. Sagar tags `plan-03`.
This is the busiest plan, with 7 of 8 members active. Friday of week 6 is the mid-plan integration day.

## Summary by member

| Member | Jira this plan | Commits | Focus |
|---|---|---|---|
| Gaurang | #69, #70, #71, #72 (100 h) | 4 | Bid screen, fee disclosure, WebSocket client, KYC upload |
| Ayush | #92–#96 (70 h) | 5 | Object storage, gateway middleware, WebSocket gateway, fan-out, reconnect |
| Naitik | #21, #22, #24 (60 h) | 4 | Lifecycle guards, CT-1 breaker, rejection taxonomy, concurrency harness |
| Sagar | #38–#41 (55 h) | 4 | Document store, submission API, verification state machine, listing gate |
| Sumit | #32 (20 h) | 2 | Anti-snipe extension, auction events |
| Jaydip | #59 (20 h) | 1 | `PaymentPort` finalised (if pulled forward in Plan 2: tests and docs only) |
| Jay | #80 (20 h) | 2 | Admin KYC review queue (API + screen) |
| Harshal | none | 1 | Pull-forward: feature extraction for the Plan 4/5 detector |

## Commits in merge order

### Week 6 — identity and gateway foundations

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 1 | Ayush | `ayush/96-object-storage` | `feat(infra): encrypted object storage with short-TTL signed-URL policy` | `libs/zeo-common/zeo_common/storage.py`, `libs/zeo-common/tests/test_storage.py`, `infra/s3/create-buckets.sh` | #96 |
| 2 | Ayush | `ayush/95-gateway-middleware` | `feat(auth): gateway dependency gating role, kyc_status and suspension` | `libs/zeo-common/zeo_common/gateway.py`, `libs/zeo-common/tests/test_gateway.py` | #95 |
| 3 | Sagar | `sagar/39-document-store` | `feat(kyc): document store storing object keys, resolved to signed URLs` | `services/kyc/app/adapters/document_store.py`, `tests/test_document_store.py` | #39 |
| 4 | Sagar | `sagar/38-kyc-submission` | `feat(kyc): submission and document upload endpoints with type, size and MIME validation` | `services/kyc/app/{api,settings}.py`, `app/domain/submission.py`, `tests/test_submission_api.py` | #38 |
| 5 | Sagar | `sagar/40-verification-sm` | `feat(kyc): verification state machine with audited transitions and forced token refresh` | `services/kyc/app/domain/verification.py`, `app/adapters/user_mirror.py`, `tests/test_verification.py` | #40 |
| 6 | Naitik | `naitik/24-lifecycle-guards` | `feat(orchestrator): lifecycle transition guards from the transition table` | `services/auction-orchestrator/app/domain/lifecycle.py`, `tests/test_lifecycle_guards.py` | #24 |
| 7 | Ayush | `ayush/92-ws-connections` | `feat(ws-gateway): authenticated WebSocket handshake and connection limits` | `services/ws-gateway/app/{api,connections}.py`, `tests/test_handshake.py` | #92 |
| 8 | Jaydip | `jaydip/59-payment-port` | `feat(payment): finalise PaymentPort with idempotency keys on every money-moving call` | `services/payment-escrow/app/payment_port/`, `tests/test_payment_port.py` | #59 |
| 9 | Gaurang | `gaurang/69-bid-screen` | `feat(frontend): auction detail and bid form with contract-mirrored validation` | `frontend/src/features/bidding/` | #69 |
| 10 | Gaurang | `gaurang/70-fee-disclosure` | `feat(frontend): live price with pre-bid flat-fee disclosure from /fees/quote (stub)` | `frontend/src/features/bidding/FeeDisclosure.tsx`, `frontend/src/mocks/fees.ts` | #70 |

### Week 7 — real time, gate and hardening

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 11 | Sagar | `sagar/41-listing-gate` | `feat(orchestrator): enforce the KYC listing gate at the service layer (CT-2)` | `services/auction-orchestrator/app/api.py`, `tests/test_listing_gate_api.py`, `contracts/openapi/internal/kyc-status.v1.yaml` | #41 |
| 12 | Jay | `jay/80-kyc-queue-api` | `feat(kyc): admin review queue, approve and reject with reason, audited document views` | `services/kyc/app/admin_api.py`, `tests/test_admin_queue.py` | #80 |
| 13 | Jay | `jay/80-kyc-queue-ui` | `feat(frontend): admin KYC review queue and document viewer` | `frontend/src/features/admin-kyc/` | #80 |
| 14 | Sumit | `sumit/32-anti-snipe` | `feat(orchestrator): anti-snipe extension capped by max_extensions` | `services/auction-orchestrator/app/domain/anti_snipe.py`, `tests/test_anti_snipe.py` | #32 |
| 15 | Sumit | `sumit/32-auction-events` | `feat(orchestrator): publish AuctionStateChanged v1 for every transition` | `services/auction-orchestrator/app/adapters/kafka_producer.py`, `tests/test_auction_events.py` | #32 |
| 16 | Ayush | `ayush/93-fanout` | `feat(ws-gateway): Kafka-driven room fan-out and outbid alerts to the displaced bidder` | `services/ws-gateway/app/{fanout,rooms}.py`, `tests/test_fanout.py` | #93 |
| 17 | Ayush | `ayush/94-reconnect` | `feat(ws-gateway): reconnect snapshot by server_seq and price coalescing under backpressure` | `services/ws-gateway/app/backpressure.py`, `tests/test_reconnect.py` | #94 |
| 18 | Naitik | `naitik/24-ct1-breaker` | `feat(bid): CT-1 circuit breaker with a 2 s state cache` | `services/bid/app/adapters/auction_client.py`, `tests/test_ct1_breaker.py` | #24 |
| 19 | Naitik | `naitik/21-rejection-taxonomy` | `feat(bid): final rejection taxonomy in the uniform error envelope` | `services/bid/app/errors.py`, `contracts/errors/bid-rejection-codes.yaml`, `tests/test_rejections.py` | #21 |
| 20 | Naitik | `naitik/22-concurrency-harness` | `test(bid): 200 bids/s contended single-auction harness with replay check` | `tests/load/concurrency_harness.py`, `tests/load/README.md` | #22 |
| 21 | Gaurang | `gaurang/71-ws-client` | `feat(frontend): WebSocket client with reconnect banner and optimistic updates` | `frontend/src/lib/ws/`, `frontend/src/features/bidding/useLivePrice.ts` | #71 |
| 22 | Gaurang | `gaurang/72-kyc-upload` | `feat(frontend): KYC upload flow with verification status strip` | `frontend/src/features/kyc/` | #72 |
| 23 | Harshal | `harshal/53-features` | `feat(fraud): feature extraction for shill signals over a sliding window` | `services/fraud-detector/app/features.py`, `tests/test_features.py` | pull-forward #53 |

**Cross-owner commits:**
- 6 is Naitik's code in Sumit's service, so Sumit approves.
- 11 is Sagar's code in Sumit's service, so Sumit approves.
- 12 is Jay's code in Sagar's service, so Sagar approves.
- 1 and 2 change the shared template, so Ayush plus one service owner approve.

## Gate (#105)

- [ ] Submit KYC → admin approves → token refresh → auction created. Unverified direct API call → `SELLER_NOT_VERIFIED`, 0 auctions created
- [ ] Signed URLs only, and no document bytes in logs. All transitions are audited
- [ ] Illegal transitions are refused. Anti-snipe extends up to the cap
- [ ] Two browsers see live prices. Outbid alert arrives. Reconnect resumes with no gap
- [ ] Fee disclosed before bidding. Harness: 200 bids/s, identical winner on replay → tag `plan-03`
