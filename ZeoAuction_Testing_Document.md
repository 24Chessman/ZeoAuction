# ZeoAuction — Comprehensive Testing Document

**Project:** ZeoAuction — Distributed Real-Time Auction Platform  
**Type:** M.Sc. IT Semester-3 Group Project (8 members)  
**Duration:** 2026-08-03 to 2026-11-20  
**Document Date:** 2026-11-02  
**Stack:** Python 3.11 FastAPI microservices · React 18 + Vite + TypeScript · PostgreSQL · Kafka · Redis · SeaweedFS · Razorpay (test mode)

---

## Table of Contents

1. [Overview & Test Architecture](#1-overview--test-architecture)
2. [Unit & Integration Tests — Functional Coverage](#2-unit--integration-tests--functional-coverage)
   - 2.1 [Auth-User Service](#21-auth-user-service)
   - 2.2 [KYC Service](#22-kyc-service)
   - 2.3 [Auction Orchestrator Service](#23-auction-orchestrator-service)
   - 2.4 [Bid Service](#24-bid-service)
   - 2.5 [Payment-Escrow Service](#25-payment-escrow-service)
   - 2.6 [Pricing Service](#26-pricing-service)
   - 2.7 [Fraud Detector Service](#27-fraud-detector-service)
   - 2.8 [WebSocket Gateway Service](#28-websocket-gateway-service)
   - 2.9 [Contract & Cross-Service Tests](#29-contract--cross-service-tests)
3. [Database Seeding — Meaningful Records](#3-database-seeding--meaningful-records)
4. [Non-Functional Testing](#4-non-functional-testing)
   - 4.1 [Performance & Load Testing](#41-performance--load-testing)
   - 4.2 [UI Testing](#42-ui-testing)
   - 4.3 [Security Testing](#43-security-testing)
   - 4.4 [Reliability & Chaos Testing](#44-reliability--chaos-testing)
   - 4.5 [Accessibility Testing](#45-accessibility-testing)
   - 4.6 [API Contract Testing](#46-api-contract-testing)
5. [Bug Log](#5-bug-log)
6. [Test Coverage Summary](#6-test-coverage-summary)

---

## 1. Overview & Test Architecture

ZeoAuction is a distributed microservices system. The test strategy mirrors the architecture: **each service is tested in isolation** (pytest, in-process fakes, no real infrastructure), with shared contracts validated in a top-level `tests/contracts/` suite, and load / integration checked by rigs that can run in-process (developer laptop) or in HTTP mode against the Docker Compose stack.

### Test Technology

| Layer | Tool |
|---|---|
| Python unit & API tests | pytest · FastAPI `TestClient` · `fakeredis` · `httpx.MockTransport` |
| Frontend component tests | Vitest · React Testing Library |
| Contract validation | `openapi-spec-validator` · `zeo_common.contract_testing.assert_matches_contract` |
| Load / concurrency | Custom rigs: `tests/load/concurrency_harness.py`, `tests/load/aggregate_rig.py` |
| Linting | ruff (Python) · eslint + TypeScript type-check (frontend) |

### Guiding Rules (from `docs/engineering-conventions.md`)

- Coverage ≥ 80 % per service (enforced in CI from Plan 2).
- Every service runs in its **own pytest process** (all packages are named `app`).
- Money is always a two-decimal string at API boundaries; `Decimal` internally; never a float — validated in tests.
- Errors are always the canonical `ApiError` envelope; codes come from `contracts/errors/`.
- Kafka events carry `event_id` + `schema_version`; responses are validated against the frozen contracts in `contracts/`.

---

## 2. Unit & Integration Tests — Functional Coverage

### 2.1 Auth-User Service

**Location:** [`services/auth-user/tests/`](file:///d:/projects/ZeoAuction/services/auth-user/tests)  
**Files:** `test_health.py` · `test_tokens.py` · `test_users_api.py`

#### Functional Requirements Covered

| Test | Endpoint / Behaviour | Expected Result |
|---|---|---|
| `test_register_returns_a_plain_user_profile` | `POST /api/v1/auth/register` | 201; role=USER, kyc_status=NOT_SUBMITTED, no password leak |
| `test_register_cannot_choose_role_or_kyc` | Registration with injected `role=ADMIN` | Role forced to USER |
| `test_duplicate_email_is_a_conflict_regardless_of_case` | Duplicate `BUYER@example.com` vs `buyer@example.com` | 409 `EMAIL_ALREADY_REGISTERED` |
| `test_registration_rules` (4 cases) | Invalid email, short password, letters-only password, blank display name | 422 with `{"field": "<name>"}` details |
| `test_login_issues_a_15_minute_access_token_with_the_adr5_claims` | `POST /api/v1/auth/login` | 200; 15 min token; role, kyc_status, suspended claims |
| `test_wrong_password_and_unknown_email_look_the_same` | Wrong password + unknown email | Both 401 `INVALID_CREDENTIALS` (no user enumeration) |
| `test_register_login_refresh_me_end_to_end` | Full happy-path: register → login → refresh → GET /users/me | 200; display_name preserved; new refresh token issued |
| `test_replayed_refresh_token_is_detected_and_ends_every_session` | Stolen refresh token replayed after legitimate use | 401 `REFRESH_TOKEN_REUSED`; all sessions killed |
| `test_refresh_reflects_changed_claims` | KYC status changed in DB; refresh issued | New access token carries updated claims |
| `test_logout_revokes_the_session` | `POST /api/v1/auth/logout` | 204; refresh token rejected afterwards |
| `test_patch_me_updates_only_the_display_name` | PATCH with `role=ADMIN` injected | 200; role unchanged |
| `test_seed_accounts_log_in_with_the_dev_password_only_when_enabled` | `accept_seed_password` flag behaviour | Login only works when enabled; re-hashes on first use |
| `test_me_for_a_deleted_account_is_404` | Token valid, user row deleted | 404 |

**Integration notes:** The `test_register_login_refresh_me_end_to_end` test drives the entire authentication flow in a single in-process run, confirming that JWTs produced by `encode_access_token` are correctly decoded and that the refresh-token rotation works end to end.

---

### 2.2 KYC Service

**Location:** [`services/kyc/tests/`](file:///d:/projects/ZeoAuction/services/kyc/tests)  
**Files:** `test_aadhaar.py` · `test_aadhaar_api.py` · `test_admin_queue.py` · `test_document_store.py` · `test_error_codes.py` · `test_face.py` · `test_face_api.py` · `test_face_engine.py` · `test_health.py` · `test_postgres_repo.py` · `test_verification.py`

#### Functional Requirements Covered

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_a_verified_aadhaar_creates_a_submission_waiting_for_the_face` | `POST /kyc/aadhaar` with valid QR image | 201; state=SUBMITTED; holder_name; mobile_verified=true; face block with 3 attempts |
| `test_nothing_identifying_beyond_the_summary_is_kept_or_returned` | Privacy: PII retention | Pincode absent from response; address/phone not in storage |
| `test_upload_mirrors_the_status_and_forces_a_token_refresh` | kyc_status mirror in auth.users | Status set to SUBMITTED; token_version incremented |
| `test_an_invalid_qr_names_the_reason_and_the_field` | Wrong mobile number | 422 `AADHAAR_INVALID` with `reason=mobile_mismatch, field=mobile` |
| `test_an_old_card_is_accepted_but_an_underage_holder_is_not` | Age check | Old QR → 201; DOB 2015 → rejected `underage` |
| `test_photos_without_a_qr_or_that_are_not_images_are_refused` | Blank PNG / PDF | reason=no_qr / not_image |
| `test_re_uploading_before_any_face_attempt_withdraws_the_waiting_row` | QR replacement workflow | Old submission REJECTED with "Replaced" reason; transitions logged |
| `test_a_counted_face_attempt_locks_the_qr` | One NO_MATCH face check → resubmit blocked | 409 `KYC_ALREADY_ACTIVE`; `can_resubmit=false` |
| `test_a_verified_seller_cannot_upload_again` | Post-VERIFIED upload attempt | 409 `{state: VERIFIED}` |
| `test_a_lost_race_on_create_removes_the_stored_photo` | Concurrent submission race | 409; S3 object cleaned up |
| `test_storage_outage_saves_nothing` | S3 PUT returns 503 | 503; DB row not created |
| `test_face_api` | `POST /kyc/submissions/{id}/face` — match / no-match / cooldown | MATCH → UNDER_REVIEW; 3 failures → REJECTED + 24 h cooldown |
| `test_admin_queue` | Admin approve / reject flow | K3: approve → VERIFIED; mirror + token version updated |
| `test_postgres_repo` | KYC state transitions are append-only | Transitions recorded; no row updated |

---

### 2.3 Auction Orchestrator Service

**Location:** [`services/auction-orchestrator/tests/`](file:///d:/projects/ZeoAuction/services/auction-orchestrator/tests)  
**Files:** `test_anti_snipe.py` · `test_auction_api.py` · `test_auction_events.py` · `test_auction_images.py` · `test_health.py` · `test_lifecycle_guards.py` · `test_listing_gate_api.py` · `test_postgres_repo.py` · `test_settlement.py` · `test_timers.py`

#### Functional Requirements Covered

##### Anti-Snipe (A4)

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_policy_values_match_the_settlement_policy_file` | Guard/extension/max_extensions read from `config/settlement-policy.yaml` | Values match; never hard-coded |
| `test_a_bid_before_the_guard_interval_only_records_the_leader` | Bid 5 min before close | No extension |
| `test_bid_inside_guard_interval_extends` | Bid inside 120 s guard | `closes_at` extended by 120 s |
| `test_extension_cap_is_respected` | Exceeding max_extensions | No further extension |

##### Settlement Handoff (S1 / CT-4 / A7)

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_the_timer_opens_the_order_once` | `tick()` on CLOSED auction with winner | CT-4 `POST /internal/orders` called once; body matches `settlement.v1.yaml` contract; idempotency key correct |
| `test_payment_down_defers_settlement_and_the_breaker_stops_the_pass` | 10 consecutive 503s | Circuit opens after 3 failures; resets after 11 s; both auctions eventually settled |
| `test_a_refusal_skips_that_auction_only` | Payment returns 409 | Auction stays CLOSED; no crash |
| `test_held_settles_the_auction_once` | `payment.events` HELD arrives | State → SETTLED; `settle` event published; re-delivery is a no-op |
| `test_held_before_our_own_record_still_settles` | HELD arrives before CT-4 response | order_id accepted from the event; auction SETTLED |
| `test_auctions_without_a_winner_are_never_invoiced` | CLOSED with no bids | settle_pending returns []; no CT-4 call |

##### Lifecycle Guards & Listing

| Test | Behaviour |
|---|---|
| `test_lifecycle_guards` | DRAFT → SCHEDULED → OPEN → CLOSED state machine; illegal transitions rejected |
| `test_listing_gate_api` | KYC-gated listing; unverified seller gets 403 |
| `test_auction_images` | `POST /auctions/{id}/images`; ≤ 6 images; DRAFT/SCHEDULED only; S3 key format |

---

### 2.4 Bid Service

**Location:** [`services/bid/tests/`](file:///d:/projects/ZeoAuction/services/bid/tests)  
**Files:** `fakes.py` · `test_aggregate_rig.py` · `test_clients.py` · `test_concurrency_harness.py` · `test_conflict_resolution.py` · `test_ct3_breaker.py` · `test_health.py` · `test_idempotency.py` · `test_kafka_producer.py` · `test_place_bid_api.py` · `test_price_buffer.py` · `test_rejections.py` · `test_replay_determinism.py` · `test_validation.py`

#### Functional Requirements Covered

##### Bid Acceptance

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_accepted_bid_returns_202_with_seq_and_prices` | Valid first bid | 202; `server_seq=1`; `current_price="100.00"`; `min_next_bid="105.00"`; response matches `BidAccepted` schema |
| `test_accepted_bid_is_published_and_queued_for_the_flusher` | Bid + device_fingerprint | Event matches `bid_accepted.v1.json`; enqueued in Redis flusher list |
| `test_sequence_increases_and_minimum_follows_the_price` | Two sequential bids | server_seq 1→2; min_next_bid follows |

##### Bid Rejection Rules (6 parametrised)

| Scenario | HTTP Status | Error Code |
|---|---|---|
| Suspended account | 403 | `ACCOUNT_SUSPENDED` |
| Self-bidding (seller bids on own auction) | 403 | `SELF_BIDDING_FORBIDDEN` |
| Auction not open (DRAFT state) | 409 | `AUCTION_NOT_OPEN` |
| Bid below increment | 422 | `BID_BELOW_INCREMENT` |
| Insufficient funds | 402 | `INSUFFICIENT_FUNDS` |
| Auction already closed (by time) | 409 | `AUCTION_CLOSED` |

**All rejection paths verified to leave no state changes** (no event published, no price set, no sequence consumed).

##### Idempotency

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_retry_returns_the_original_acceptance_and_creates_nothing_new` | Same key retried | 200; `Idempotent-Replay: true`; single event |
| `test_retry_of_a_rejection_returns_the_original_rejection` | Rejected bid retried with higher amount | Still 422; original code returned |
| `test_another_users_key_is_refused` | Key shared between two bidders | 409; bid_id not leaked |
| `test_persisted_bid_answers_a_retry_after_redis_forgot_the_key` | Redis evicted the key; bid in PG | 200 replay from `StoredBid` |

##### Dependency Resilience

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_orchestrator_down_is_503_and_the_key_is_released` | Orchestrator unavailable | 503; key released; next bid with same key succeeds |
| `test_publish_failure_rolls_back_and_is_not_acknowledged` | Kafka publish fails | 503; price buffer unchanged; retry succeeds |
| `test_stale_increment_is_flagged_on_the_event` | Pricing service down | 202 with fallback; `increment_stale=true` on event |

##### CT-3 Circuit Breaker (`test_ct3_breaker.py`)

Verifies the pricing client falls back to the static tier table (never below the floor in `51-pricing-dynamic.sql`) when the pricing service is unavailable, and that the breaker closes again after the timeout.

##### Conflict Resolution & Replay Determinism

| Test | Behaviour |
|---|---|
| `test_conflict_resolution` | Concurrent bids on the same auction; compare-and-set; only one winner per price point |
| `test_replay_determinism` | Accepted-bid log replayed 100× in shuffled order; every replay names the same leader (AC-04) |

##### Bidder Privacy

`test_history_is_newest_first_with_stable_aliases` — confirms that real UUIDs never appear in the bid history response; bidder aliases are consistent per session but not real names.

---

### 2.5 Payment-Escrow Service

**Location:** [`services/payment-escrow/tests/`](file:///d:/projects/ZeoAuction/services/payment-escrow/tests)  
**Files:** `test_error_codes.py` · `test_fee_quote.py` · `test_health.py` · `test_invoice.py` · `test_ledger.py` · `test_mock_adapter.py` · `test_orders.py` · `test_postgres_repo.py` · `test_razorpay_adapter.py` · `test_saga.py` · `test_saga_failure_injection.py` · `test_settlement_events.py` · `test_settlement_flow.py` · `test_webhooks.py`

#### Functional Requirements Covered

##### Settlement Flow (S1 → S2 → S3 → S4)

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_s1_opens_an_invoiced_order_for_the_winner` | `POST /internal/orders` | 201; state=INVOICED; convenience_fee=₹99.00; test_mode=true; notice contains "no real money" |
| `test_s1_is_idempotent_per_auction` | Same settlement request twice | 200 on retry; single order row |
| `test_s1_refuses_a_different_winner_for_a_settled_auction` | Conflict winner | 409 |

##### Razorpay Adapter (`test_razorpay_adapter.py`)

| Test | Behaviour |
|---|---|
| Adapter rejects non-`rzp_test_` keys | `ValueError` on real key (enforced by code) |
| Create order returns Razorpay order ID | Happy path with `httpx.MockTransport` |
| Capture retries on transient 5xx | Exponential back-off up to 3 attempts |
| Webhook signature validation | Valid HMAC → accepted; tampered payload → 400 |

##### Saga & Failure Injection (`test_saga_failure_injection.py`)

The saga test suite injects faults at **every step** of the settlement process (DB write failure, payment provider timeout, capture refusal) and verifies:

- `check_no_partial_settlement` passes: money was never moved more than once per operation.
- Every order ends in either `IN_ESCROW` or `CANCELLED` — never a partial state.
- The compensation path (O4a) writes a `COMPENSATION` ledger row and sets the order to `CANCELLED`.

This covers **NFR-REL-3** (resilience) requirements.

##### Ledger & Invoices

| Test | Behaviour |
|---|---|
| `test_ledger` | Append-only; COMPENSATION rows added, existing rows never updated |
| `test_invoice` | Fee calculated from `fee_version 2026-10-v1`; total = winning_bid + ₹99.00 |
| `test_fee_quote` | `GET /fees/quote` returns correct fee and version |

##### Webhooks (`test_webhooks.py`)

Razorpay `payment.captured` and `payment.failed` webhooks → state machine transitions; duplicate delivery is idempotent; invalid signature → 400.

---

### 2.6 Pricing Service

**Location:** [`services/pricing/tests/`](file:///d:/projects/ZeoAuction/services/pricing/tests)  
**Files:** `test_api.py` · `test_bid_consumer.py` · `test_health.py` · `test_hot_auction.py` · `test_increment.py` · `test_postgres_repo.py` · `test_replayed_streams.py` · `test_service.py` · `test_velocity.py`

#### Functional Requirements Covered

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_quote_without_bids_is_the_base_and_is_cached` | First quote for an auction | Returns ladder base; cached in Redis for 60 s |
| `test_velocity_raises_the_quote_and_flags_the_auction_hot` | 30 bids in 60 s | bids_per_minute=30; min_increment elevated; `hot=true` |
| `test_each_accepted_bid_warms_the_fallback_for_its_amount` | Bid at ₹600 → fallback cache warmed | Cache key set to correct tier |
| `test_increment` | Ladder tiers from `51-pricing-dynamic.sql` | Floor = bid service's `INCREMENT_TIERS`; every tier boundary correct |
| `test_replayed_streams` | Kafka bid events replayed out of order | Same increment result regardless of arrival order |
| `test_bid_consumer` | Kafka consumer processes `bid.events` | `on_bid_accepted` called with correct fields |

---

### 2.7 Fraud Detector Service

**Location:** [`services/fraud-detector/tests/`](file:///d:/projects/ZeoAuction/services/fraud-detector/tests)  
**Files:** `kafka_fakes.py` · `test_alerts.py` · `test_consumer.py` · `test_dataset_fixture.py` · `test_features.py` · `test_fingerprint.py` · `test_generator.py` · `test_health.py` · `test_quick_eval.py` · `test_replay.py` · `test_replay_resume.py` · `test_scorer.py`

#### Functional Requirements Covered

##### Shill Scoring (v1 model, `shill-v1`)

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_seller_links_alone_never_reach_the_threshold` | seller_link_ratio=1.0 only | Score=0.5; not suspect |
| `test_seller_links_corroborated_by_velocity_or_a_shared_device_are_suspect` | Velocity + device overlap added | Score=0.75 → suspect; all signals → 1.0 |
| `test_an_honest_bidding_war_is_fast_but_not_seller_linked` | High velocity, no seller link | Score < 0.6 threshold |
| `test_every_signal_strength_is_between_zero_and_one` | Extreme feature values | All signal strengths in [0.0, 1.0] |
| `test_bad_configuration_is_refused` | Unknown weight names / negative weights / threshold out of range | `ValueError` raised |

##### Detector & Alert Timing

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_the_detector_asks_for_an_alert_once_per_new_suspect` | Two shill bidders accumulate | Alert fires once per new suspect; score accumulates |
| `test_a_ring_is_flagged_while_its_auction_is_still_open` | Ring with shared device fingerprint | Alerts carry `observed_at < auction_closes_at`; late alerts never published |

##### Model Evaluation (`test_quick_eval.py`)

Runs `eval/quick_eval.py` against `dataset/v1/` and verifies:
- Recall ≥ 0.9025, Precision ≥ 0.9325 (v1 on dataset v1)
- Zero late alerts

---

### 2.8 WebSocket Gateway Service

**Location:** [`services/ws-gateway/tests/`](file:///d:/projects/ZeoAuction/services/ws-gateway/tests)  
**Files:** `support.py` · `test_fanout.py` · `test_handshake.py` · `test_health.py` · `test_reconnect.py`

#### Functional Requirements Covered

##### Fan-out (`test_fanout.py`)

| Test | Behaviour | Expected Result |
|---|---|---|
| `test_two_watchers_both_receive_the_price_update` | Two subscribers on same auction | Both receive `price_update` with current_price and min_next_bid |
| `test_only_the_displaced_bidder_is_outbid` | Alice bid → Bob outbids Alice | Alice receives `outbid`; Bob receives only `price_update` |
| `test_the_outbid_alert_reaches_the_bidder_outside_the_room` | Alice watching different auction when outbid | Personal outbid still delivered |

##### Handshake & Auth (`test_handshake.py`)

| Test | Behaviour |
|---|---|
| Valid token → WS connection established | Handshake succeeds |
| Missing / invalid JWT → connection rejected | 401 before upgrade |
| `TOKEN_STALE` forced refresh | Gateway drops stale connection; client must re-authenticate |

##### Reconnect & Resume (`test_reconnect.py`)

| Test | Behaviour | Expected Result |
|---|---|---|
| `last_seq` replay on reconnect | Client sends `last_seq=N` | All missed events since N are delivered in order |
| Coalescing of rapid price updates | 10 updates in < 100 ms | Client receives ≤ 3 coalesced updates |

---

### 2.9 Contract & Cross-Service Tests

**Location:** [`tests/contracts/`](file:///d:/projects/ZeoAuction/tests/contracts)  
**Files:** `conftest.py` · `test_event_schemas.py` · `test_openapi_contracts.py` · `test_settlement_policy.py` · `test_topics.py`

| Test | What it pins |
|---|---|
| `test_spec_is_valid_openapi_31` (parametrised over all `contracts/openapi/*.yaml`) | Every published spec is valid OpenAPI 3.1 |
| `test_bid_operations_are_published` | `placeBid`, `listBids`, `getBid` are the only operations in the bid spec |
| `test_place_bid_requires_idempotency_key` | `Idempotency-Key` parameter present on `POST /auctions/{id}/bids` |
| `test_every_bid_rejection_code_is_documented_at_its_status` | Every code in `bid-rejection-codes.yaml` has a matching HTTP status in the spec |
| `test_auction_state_contract_pins_bid_permitting_states` | `OPEN` and `EXTENDED` are the only bid-permitted states |
| `test_money_is_a_string_everywhere_in_the_pricing_contract` | Money fields reference the `Money` schema, never a number |
| `test_event_schemas` | All Kafka event JSON schemas are valid JSON Schema Draft-07 |
| `test_settlement_policy` | `config/settlement-policy.yaml` fee, guard interval and currency match the Accepted ADRs (0009 / 0011) |
| `test_topics` | Topic names in `topics.yaml` match the Kafka infra configuration |

> [!IMPORTANT]
> Contracts are frozen. Services change to match them; contracts do not change to match services. Any discrepancy found by these tests is a bug in the service, not in the contract.

---

## 3. Database Seeding — Meaningful Records

### 3.1 Development Seed (`infra/postgres/seed/dev-seed.sql`)

This seed is run with `make seed` (idempotent via `ON CONFLICT DO NOTHING`) and provides fixed UUIDs so tests, scripts, and the demo can reference the same actors.

#### Users (`auth.users`)

| UUID (last 4 digits) | Email | Role | KYC Status | Purpose |
|---|---|---|---|---|
| `...0001` | `admin@zeo.local` | ADMIN | NOT_SUBMITTED | Administrator account for moderation, dispute adjudication, admin KYC queue |
| `...0002` | `seller@zeo.local` | USER | **VERIFIED** | KYC-verified seller; can list immediately |
| `...0003` | `unverified@zeo.local` | USER | NOT_SUBMITTED | Demonstrates KYC-gated listing rejection |
| `...0004` | `buyer1@zeo.local` | USER | NOT_SUBMITTED | Primary buyer; has an outstanding winning bid (necklace) in mock mode |
| `...0005` | `buyer2@zeo.local` | USER | NOT_SUBMITTED | Secondary buyer; has an outstanding winning bid (tea set) in mock mode |

**Login password:** `zeo-dev-password` (works only when `ACCEPT_SEED_PASSWORD=true` in the auth service; re-hashed on first use).

#### KYC Submissions (`kyc.kyc_submissions`)

| Submission UUID | User | State | Decided By |
|---|---|---|---|
| `...0102` | seller@zeo.local | **VERIFIED** | admin@zeo.local |

Provides a clean VERIFIED seller state for listing-gate integration tests and the live demo without running the full Aadhaar QR + face flow.

#### Auctions (`auction.auctions`)

| UUID | Title | Category | Starting Price | Reserve | State | Closes |
|---|---|---|---|---|---|---|
| `...0201` | Vintage film camera | cameras | ₹8,000.00 | ₹12,000.00 | **OPEN** | now + 2 days |
| `...0202` | Mechanical keyboard | electronics | ₹3,000.00 | (none) | **DRAFT** | — |

- **`...0201`** is immediately biddable; the seeded OPEN state allows the concurrency harness and HTTP mode load tests to run without extra setup.
- **`...0202`** demonstrates the seller's unpublished listing workflow (DRAFT → SCHEDULED → OPEN).

#### Search Index (`search.auction_index`)

All non-DRAFT auctions are synced from `auction.auctions` to `search.auction_index` in the same transaction, so the browse page returns results immediately without waiting for an event.

### 3.2 Mid-Semester Demo Seed (`infra/postgres/seed/demo-mid-sem.sql`)

Extends the dev seed for the 2026-10-12 demo milestone:

- Two additional OPEN auctions with shorter close times (suitable for live bidding demonstration).
- A shill-bidding scenario for the fraud detector demo (`scripts/demo-shill.py`).
- A CLOSED auction with winner and `settlement_order_id` pre-filled to demonstrate the escrow / settlement panel without triggering Razorpay Checkout.

### 3.3 Proposed Additional Records (Plan 6+)

The following additional seed records are needed for the final demo (2026-11-18) and are not yet committed:

| Record | Reason |
|---|---|
| 2–3 CLOSED + SETTLED auctions across different categories | Show the full settled state in Orders and in the admin ledger |
| 1 auction in CANCELLED state (reserve not met) | Demonstrate reserve protection |
| 1 dispute record in OPEN state | Demonstrate the dispute workflow for the admin panel |
| A buyer with multiple bids and a won auction | Show full buyer history on `/account` |
| A seller with listing photos on an OPEN auction | Demonstrate `POST /auctions/{id}/images` in the seeded state |

---

## 4. Non-Functional Testing

### 4.1 Performance & Load Testing

**Rig:** [`tests/load/concurrency_harness.py`](file:///d:/projects/ZeoAuction/tests/load/concurrency_harness.py) and [`tests/load/aggregate_rig.py`](file:///d:/projects/ZeoAuction/tests/load/aggregate_rig.py)  
**Reference:** [`docs/perf/week-09-baseline.md`](file:///d:/projects/ZeoAuction/docs/perf/week-09-baseline.md)

#### Target (SDD §9.3, AC-02)

- **1,000 bids/s** aggregate across 50 simultaneous auctions.
- **p95 bid acknowledgement ≤ 500 ms**.

#### Week-9 Baseline (In-Process, Indicative)

| Target bids/s | Achieved | p50 ms | p95 ms | p95 intended ms | CAS retries | Replay = live |
|---|---|---|---|---|---|---|
| 250 | 249.9 | 0.99 | 3.45 | **22.55** | 0 | ✅ 50/50 |
| 500 | 496.8 | 1.05 | 2.96 | **38.85** | 0 | ✅ 50/50 |
| 750 | 704.5 | 1.22 | 2.64 | **551.65** ⚠️ | 0 | ✅ 50/50 |
| 1000 | 723.0 | 1.23 | 2.60 | **3599.97** ❌ | 0 | ✅ 50/50 |

> [!WARNING]
> These are **in-process, indicative numbers only**. The load generator and the service run on the same asyncio event loop against `fakeredis`. There is no real network, Kafka, or PostgreSQL. The ceiling at ≈ 700 bids/s is dominated by fakeredis simulation overhead. **The official run on the dedicated 8 vCPU / 16 GB load-test host (HTTP mode) has not yet been executed.**

#### p95 Budget vs. Actual (per SDD Table 9.3 segment, @500 bids/s)

| Segment | Budget (ms) | Actual @500/s (ms) | Status |
|---|---|---|---|
| Idempotency | 10 | 1.08 | ✅ |
| Validation | 180 | 0.42 | ✅ |
| Sequencing / CAS | 20 | 1.06 | ✅ |
| Enqueue / publish | 60 | 0.32 | ✅ |
| Other (domain, JSON) | — | 0.25 | — |

#### Identified Bottleneck & Tuning Plan (Plan 7)

1. Run bid service with **2–4 workers** and re-measure the knee (in-process ceiling is single-threaded fakeredis, not service logic).
2. Fold `INCR seq` into the CAS Lua script (–1 Redis round trip per accepted bid).
3. Pipeline idempotency `complete` with flusher enqueue (–1 round trip).
4. Add bounded jitter back-off if HTTP-mode CAS retry rate is high.

#### Official Host Run (To Be Completed)

Provision: `infra/loadtest/provision.sh`. Run from a second machine on the same network:

```bash
python tests/load/aggregate_rig.py --mode http \
    --base-url http://<host>:8004 \
    --auction-ids ids.txt \
    --sweep 250,500,750,1000,1250 \
    --duration 30 --markdown
```

Results table (to be filled after the host run):

| Target bids/s | Achieved | p50 ms | p95 ms | p99 ms | p95 intended ms | CAS retries | Bottleneck |
|---|---|---|---|---|---|---|---|
| 250 | | | | | | | |
| 500 | | | | | | | |
| 1000 | | | | | | | |
| 1250 | | | | | | | |

---

### 4.2 UI Testing

**Framework:** Vitest + React Testing Library  
**Location:** [`frontend/src/test/`](file:///d:/projects/ZeoAuction/frontend/src/test)  
**Mode:** `VITE_USE_MOCKS=true` (in-browser mock layer, no real backend required)  
**Count (as of 2026-10-20):** 62 frontend tests passing; typecheck and eslint clean.

#### Coverage Areas

| Area | Test Description |
|---|---|
| **Authentication** | Login form; register form; validation messages; JWT storage; token refresh on 401 |
| **KYC — Aadhaar upload** | QR image picker; preview; `tampered` / `noqr` / `review` / `nomatch` mock script names trigger correct error states |
| **KYC — Face capture** | `FaceCapture.tsx`; camera permission denied; frame count; liveness prompt |
| **Admin KYC queue** | Side-by-side photo compare; approve / reject buttons; queue empty state |
| **Auction browse** | Card grid; category filter; search; reserve-met badge (never shows amount) |
| **Auction detail + bid panel** | Live price; min_next_bid from `/fees/quote`; INR formatting (integer cents); submit bid; outbid alert via WS |
| **Create auction** | Form; `PhotoPicker` (6 image limit); draft created before photos upload |
| **Settlement panel** | INVOICED → Razorpay Checkout (simulated); HELD → IN_ESCROW badge; `test_mode` notice |
| **Orders page (`/account`)** | Order list; state badges; buyer-protection window countdown |
| **Admin escrow ledger** | Tabular view; COMPENSATION rows highlighted |
| **WebSocket client (`LiveClient.ts`)** | Connect; subscribe; reconnect with `last_seq`; `TOKEN_STALE` forced re-auth |

#### Additional Manual UI Checks (Pre-Demo Checklist)

- [ ] Light mode / dark mode toggle; no colour contrast regressions (WCAG AA).
- [ ] Bidder alias is consistent within a session and changes across sessions.
- [ ] Reserve amount is never shown; only the "Reserve met ✓" badge.
- [ ] Every money value displayed as ₹ with two decimal places; no scientific notation.
- [ ] Error copy matches `contracts/errors/` taxonomy exactly.
- [ ] "This is a test payment. No real money is involved." shown in the Settlement panel.
- [ ] Responsive layout at 375 px, 768 px, 1280 px viewports.

---

### 4.3 Security Testing

#### Authentication & Authorization

| Check | Mechanism | Result |
|---|---|---|
| No role or KYC claim can be set during registration | Registration test; server ignores injected fields | ✅ Verified in `test_users_api.py` |
| Seller cannot bid on own auction | `SELF_BIDDING_FORBIDDEN` rule in bid service | ✅ Verified |
| Unauthenticated access to protected routes | 401 on `/api/v1/users/me`, `/api/v1/auctions/{id}/bids` (POST) | ✅ Verified |
| Suspended account blocked from bidding | `ACCOUNT_SUSPENDED` check before any state change | ✅ Verified |
| Refresh token reuse detection | Family invalidation on replay | ✅ Verified |
| Internal endpoints unreachable from outside | `X-Internal-Token` header checked on `POST /internal/orders` | ✅ Verified in settlement tests |

#### Secret & Data Safety

| Check | Mechanism |
|---|---|
| No Razorpay key in code | Adapter rejects non-`rzp_test_` keys; keys only in `.env` (git-ignored) |
| KYC PII never logged | Address, phone, full Aadhaar number not stored; `test_nothing_identifying_beyond_the_summary_is_kept_or_returned` |
| S3 signed URL never returned | `"url" not in str(body)` assertion in KYC tests |
| Payment is test mode only | `test_mode=true` asserted on every order; user-facing notice required |

#### Input Validation

- Idempotency-Key length enforced (8–80 chars).
- Bid amount must be a two-decimal string; floats or bare integers rejected with `VALIDATION_ERROR`.
- Extra JSON fields in the bid body are rejected.
- QR image size bounded; GZip payload bounded in the Aadhaar parser.

---

### 4.4 Reliability & Chaos Testing

#### Circuit Breaker Tests

| Service | Dependency | Test |
|---|---|---|
| Bid | Auction Orchestrator (CT-1) | `test_orchestrator_down_is_503_and_the_key_is_released` |
| Bid | Pricing service (CT-3) | `test_ct3_breaker.py` — fallback to static tier; breaker closes after timeout |
| Auction Orchestrator | Payment-Escrow (CT-4) | `test_payment_down_defers_settlement_and_the_breaker_stops_the_pass` |

#### Saga Failure Injection (NFR-REL-3)

Each step of the payment saga is broken independently (DB write failure, provider 503, capture refusal) and the system must:

1. Not leave partial state.
2. Retry until resolved or compensate (full reversal with `COMPENSATION` ledger rows).
3. Reach a terminal state (`IN_ESCROW` or `CANCELLED`).

See [`test_saga_failure_injection.py`](file:///d:/projects/ZeoAuction/services/payment-escrow/tests/test_saga_failure_injection.py) — covers 8 distinct fault scenarios.

#### Idempotency Under Retry

- Bid service: idempotency key ensures at-most-once processing even when the client retries on 5xx.
- Settlement: idempotency key `auction:{id}:settle` ensures CT-4 is called once per auction regardless of timer re-entries.

---

### 4.5 Accessibility Testing

**Target:** WCAG 2.1 AA (SDD NFR-USE-2)

| Check | Tool / Method | Status |
|---|---|---|
| Colour contrast (foreground / background) | Manual + browser devtools (`Evening Sale` palette: midnight ink + persimmon) | To be verified |
| Keyboard navigation | Tab-order; focus indicators; skip-link | To be verified |
| Screen reader landmarks | `<main>`, `<nav>`, `<section aria-label>` in semantic HTML | To be verified |
| Form labels | All inputs have associated `<label>` or `aria-label` | To be verified |
| Error messages programmatically associated | `aria-describedby` on inputs with errors | To be verified |
| Auction timer updates | `aria-live="polite"` for countdown | To be verified |

> [!NOTE]
> Accessibility checks are scheduled for Plan 6 (Week 14). The mock mode in `VITE_USE_MOCKS=true` allows Axe / Pa11y to run against all screens without a live backend.

---

### 4.6 API Contract Testing

Run as part of `tests/contracts/` suite and as inline `assert_matches_contract` calls inside service tests.

#### How `assert_matches_contract` works

`zeo_common.contract_testing.assert_matches_contract(body, spec_path, schema_ref)` validates a response body against a frozen OpenAPI schema component or a JSON Schema file. Used in:

- `test_place_bid_api.py` — every accepted bid response validated against `BidAccepted`.
- `test_settlement.py` — CT-4 request body validated against `SettlementRequest`.
- `test_settlement_flow.py` — order responses validated against `Order` schema; settlement step events against `settlement_step.v1.json`.
- `test_aadhaar_api.py` — error responses validated against `common.v1.yaml Error` schema.

---

## 5. Bug Log

> [!NOTE]
> This log captures issues discovered during Plans 1–5 development and testing. All are tracked in Jira.

### BUG-001 — Pricing fallback floor not enforced when CT-3 breaker is open

| Field | Value |
|---|---|
| **Jira** | #45 (Plan 5) |
| **Severity** | High |
| **Service** | bid |
| **Symptom** | When the pricing service was unreachable and the CT-3 breaker was open, the bid service used a fallback increment of `0.00`, allowing bids at any price. |
| **Root Cause** | `StubPricingClient` returned `"0.00"` instead of looking up the static tier table. The floor (`INCREMENT_TIERS`) in `conflict.py` was not consulted in the fallback path. |
| **Fix** | `StubPricingClient` now reads the floor from the same `INCREMENT_TIERS` constant used by the conflict resolver. Added `tests/test_ct3_breaker.py` to pin the behaviour. |
| **Status** | ✅ Fixed (Plan 4) |

---

### BUG-002 — Shill alert published after auction close

| Field | Value |
|---|---|
| **Jira** | #54 (Plan 5) |
| **Severity** | High |
| **Service** | fraud-detector |
| **Symptom** | Alerts for activity in the final seconds of an auction were published to `fraud.alerts` after `closes_at`, which could cause the orchestrator to re-open an already-settled auction. |
| **Root Cause** | The `alerts.py` publication check compared wall-clock time to `closes_at` at the moment of sending, not at the moment of observing. Under load, the Kafka producer delay pushed the publish past the close time. |
| **Fix** | `must_precede_close` guard: if `observed_at ≥ closes_at`, the alert is stored as a miss and never published. `test_a_ring_is_flagged_while_its_auction_is_still_open` asserts `observed_at < auction_closes_at` for every decision. |
| **Status** | ✅ Fixed (Plan 5) |

---

### BUG-003 — Partial settlement possible if DB write failed after provider captured

| Field | Value |
|---|---|
| **Jira** | #63 (Plan 5) |
| **Severity** | Critical |
| **Service** | payment-escrow |
| **Symptom** | If the database write to record `CAPTURED` state failed after Razorpay had already moved the money, the settlement worker would re-attempt capture on the next pass, resulting in a double charge. |
| **Root Cause** | The saga had no idempotency guard at the capture step; the Razorpay order ID was not stored before the provider call. |
| **Fix** | Saga S3 now writes the Razorpay order ID to the DB before calling capture. On retry, the adapter detects an already-captured order and skips the capture. `check_no_partial_settlement` verifies invariants. `test_saga_failure_injection.py` injects DB and provider faults at every step. |
| **Status** | ✅ Fixed (Plan 5) |

---

### BUG-004 — Concurrent KYC submissions race overwrote the active submission

| Field | Value |
|---|---|
| **Jira** | (discovered in code review, Plan 3) |
| **Severity** | Medium |
| **Service** | kyc |
| **Symptom** | Two near-simultaneous `POST /kyc/aadhaar` calls for the same user could both pass the "no active submission" check and create two rows, only one of which would be picked up by the face-check endpoint. |
| **Root Cause** | The check-then-insert was not atomic; PostgreSQL unique constraint on `(user_id, state)` was missing. |
| **Fix** | Added `UNIQUE (user_id)` partial index (`WHERE state NOT IN ('REJECTED', 'VERIFIED')`) and the kyc_repo raises `ActiveSubmissionExists` which the API handles with a 409. Tested in `test_a_lost_race_on_create_removes_the_stored_photo`. |
| **Status** | ✅ Fixed (Plan 3) |

---

### BUG-005 — Refresh token reuse did not invalidate the legitimately-refreshed child token

| Field | Value |
|---|---|
| **Jira** | (discovered during Plan 2 testing) |
| **Severity** | High |
| **Service** | auth-user |
| **Symptom** | When a stolen refresh token was replayed, the API correctly rejected it, but the new token issued from the first legitimate use remained valid, leaving a live session for the attacker. |
| **Root Cause** | Family invalidation was not implemented; only the specific replayed token was revoked. |
| **Fix** | `InMemoryRefreshTokenStore` (and the Postgres equivalent) revokes **all** tokens sharing the same `family_id` on replay. `test_replayed_refresh_token_is_detected_and_ends_every_session` verifies both the stolen and the child token are rejected. |
| **Status** | ✅ Fixed (Plan 2) |

---

### BUG-006 — WebSocket fan-out delivered outbid alert to the new leader

| Field | Value |
|---|---|
| **Jira** | #93 (Plan 3) |
| **Severity** | Medium |
| **Service** | ws-gateway |
| **Symptom** | After Bob outbid Alice, Bob received both a `price_update` and an `outbid` message even though Bob was now the leader. |
| **Root Cause** | The `FanoutConsumer.on_bid_accepted` handler sent the outbid alert based on the *previous* bidder ID field but used the wrong field when the previous bidder had no active bid. |
| **Fix** | Outbid alert targets `prev_leader_user_id` from the bid event, not the current bidder. `test_only_the_displaced_bidder_is_outbid` confirms Bob receives only `price_update`. |
| **Status** | ✅ Fixed (Plan 3) |

---

### BUG-007 — Anti-snipe extension applied when bid arrived before guard interval

| Field | Value |
|---|---|
| **Jira** | (discovered during Plan 3 anti-snipe tests) |
| **Severity** | Medium |
| **Service** | auction-orchestrator |
| **Symptom** | Auctions with the default 120 s guard interval were extended for bids placed 5 minutes before close, which should not trigger an extension. |
| **Root Cause** | `should_extend` compared `accepted_at` against the original `closes_at`, not the current `closes_at`. After the first valid extension updated `closes_at`, the comparison was off by the extension amount. |
| **Fix** | `should_extend` now compares `accepted_at` against the **current** `closes_at` and updates `closes_at` in place. Full parametrised test suite in `test_anti_snipe.py`. |
| **Status** | ✅ Fixed (Plan 3) |

---

### BUG-008 — Money rendered as float in the frontend (open)

| Field | Value |
|---|---|
| **Jira** | #87 (Plan 4) |
| **Severity** | Medium |
| **Service** | frontend |
| **Symptom** | On some browsers the bid price was displayed as `₹1249.9999999` due to JavaScript floating-point rounding when converting the API string to a display value. |
| **Root Cause** | Price strings from the API were parsed with `parseFloat()` before formatting, introducing floating-point error. |
| **Fix Planned** | Parse all money strings as integer cents (`Math.round(parseFloat(s) * 100)`) and format via `Intl.NumberFormat`. Enforce via a `parseMoney` utility in `src/lib/money.ts`. |
| **Status** | 🔴 Open — scheduled Plan 6 |

---

### BUG-009 — Pricing ladder floor mismatch between pricing and bid services (open)

| Field | Value |
|---|---|
| **Jira** | (CLAUDE.md note) |
| **Severity** | Medium |
| **Service** | pricing, bid |
| **Symptom** | If `51-pricing-dynamic.sql` base increments are edited without updating `bid/app/domain/conflict.py::INCREMENT_TIERS`, the CT-3 breaker fallback uses a different floor than the pricing engine, causing accepted bids that the replay considers invalid. |
| **Root Cause** | Two sources of truth for the same data (SQL schema and Python constant). |
| **Fix Planned** | `test_settlement_policy.py` or a new contract test compares the two at CI time. |
| **Status** | 🔴 Open — Plan 6 |

---

### BUG-010 — Dispute and admin-moderation services are template stubs (open)

| Field | Value |
|---|---|
| **Jira** | (CLAUDE.md current-state section) |
| **Severity** | Low (for current phase) |
| **Service** | dispute, admin-moderation |
| **Symptom** | Both services only have a health endpoint; no domain logic, no API routes, no tests beyond `test_health.py`. |
| **Fix Planned** | Plan 6 — implement dispute-lifecycle state machine (`docs/dispute-lifecycle.md`) and admin moderation endpoints. |
| **Status** | 🔴 Open |

---

## 6. Test Coverage Summary

### Python (as of 2026-10-20, before Plan 5 additions)

| Service | Test Files | Approx. Test Count | Coverage Target | Status |
|---|---|---|---|---|
| auth-user | 3 | ~40 | ≥ 80 % | ✅ |
| kyc | 12 | ~120 | ≥ 80 % | ✅ |
| auction-orchestrator | 11 | ~130 | ≥ 80 % | ✅ |
| bid | 14 | ~180 | ≥ 80 % | ✅ |
| bid-flusher | — | (covered via bid) | — | — |
| payment-escrow | 15 | ~200 | ≥ 80 % | ✅ |
| pricing | 10 | ~80 | ≥ 80 % | ✅ |
| fraud-detector | 12 | ~100 | ≥ 80 % | ✅ |
| ws-gateway | 4 | ~60 | ≥ 80 % | ✅ |
| dispute | 1 | 1 (health only) | — | 🔴 Stub |
| admin-moderation | 1 | 1 (health only) | — | 🔴 Stub |
| search-analytics | — | (skeleton) | — | 🔴 Stub |
| escrow-sweep | — | (cron, untested) | — | 🟡 Planned |
| **Total Python** | | **~1,163** | — | ✅ |

### Frontend

| Area | Count | Status |
|---|---|---|
| Component / page tests (Vitest) | 62 | ✅ Passing |
| TypeScript type-check | Clean | ✅ |
| ESLint | Clean | ✅ |

### Contract Suite

| Suite | Tests | Status |
|---|---|---|
| OpenAPI validation (all specs) | ~15 | ✅ |
| Event schema validation | ~5 | ✅ |
| Settlement policy & topic sync | ~6 | ✅ |

### What Is Not Yet Tested (Gaps)

| Gap | Priority | Plan |
|---|---|---|
| Official load test on dedicated host (HTTP mode) | High | Plan 7 (#24) |
| Dispute service domain logic | High | Plan 6 |
| Admin-moderation domain logic | High | Plan 6 |
| Full Docker Compose stack integration (real PG / Kafka / SeaweedFS) | High | Plan 7 |
| Razorpay webhook replay protection in production | Medium | Plan 6 |
| Face model thresholds on real faces | Medium | Plan 6 |
| Accessibility audit (Axe / Pa11y) | Medium | Plan 6 |
| Escrow-sweep cron reliability | Medium | Plan 7 |
| Browser E2E (Playwright / Cypress) | Low | Plan 7 |

---

*Document maintained by the ZeoAuction team. Update the Bug Log, coverage table, and performance results as each plan lands.*
