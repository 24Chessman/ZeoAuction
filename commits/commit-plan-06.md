# Commit plan — Plan 6: Disputes, Search & Admin (weeks 12–13, Oct 19 – Oct 30)

**Status: projected.** **Milestone:** #108 *Disputes, Search and Admin integrated*. Jay tags `plan-06`.
**Checkpoint:** #113 week-13 audit (Sumit). **Feature freeze: Oct 30.**

## Summary by member

| Member | Jira this plan | Commits | Focus |
|---|---|---|---|
| Jay | #81, #82, #83, #84 (95 h) | 6 | Dispute service, adjudication API and console, listing queue, suspension |
| Gaurang | #73, #74, #75 (70 h) | 3 | Dispute form, notification tray, seller dashboard |
| Jaydip | #65, #66 (50 h) | 3 | Release (3 triggers), refund with fee-by-fault, reconciliation routine |
| Harshal | #55, #56 (50 h) | 3 | Ring clustering, fraud-triggered disputes with bid trace, re-measurement |
| Sagar | #46, #47 (30 h) | 3 | Search projection consumer, search API, browse screen wired to it |
| Naitik | #25 (25 h) | 2 | Escrow sweep and its 5-minute guarantee |
| Sumit | #35, #113 (15 h) | 2 | Terminal transitions, week-13 note |
| Ayush | #97 (10 h) | 2 | Render cron for the sweep, notifications endpoint |

## Commits in merge order

### Week 12

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 1 | Jay | `jay/84-dispute-service` | `feat(dispute): window-gated dispute creation with freeze command to Payment` | `services/dispute/app/{api,settings}.py`, `app/domain/dispute.py`, `app/adapters/payment_client.py`, `tests/test_raise_dispute.py` | #84 |
| 2 | Jaydip | `jaydip/65-release` | `feat(payment): release execution for buyer-confirm, sweep-expiry and adjudication triggers` | `services/payment-escrow/app/domain/release.py`, `app/api.py`, `tests/test_release.py` | #65 |
| 3 | Sumit | `sumit/35-terminal-transitions` | `feat(payment): RELEASED and REFUNDED are terminal, later events refused` | `services/payment-escrow/app/domain/order_state.py`, `tests/test_terminal_states.py` | #35 |
| 4 | Naitik | `naitik/25-escrow-sweep` | `feat(escrow-sweep): release expired protection windows idempotently` | `services/escrow-sweep/app/sweep.py`, `app/adapters/{orders_reader,payment_client}.py`, `tests/test_sweep.py` | #25 |
| 5 | Ayush | `ayush/97-render-cron` | `build(render): escrow-sweep as a Render Cron Job every minute` | `render.yaml` | #97 |
| 6 | Sagar | `sagar/46-search-index` | `feat(search): projection consumer maintaining auction_index and its search_vector` | `services/search-analytics/app/adapters/projection_consumer.py`, `tests/test_projection.py` | #46 |
| 7 | Harshal | `harshal/55-ring-clustering` | `feat(fraud): bid-ring clustering across auctions from fingerprints and seller graph` | `services/fraud-detector/app/clustering.py`, `tests/test_clustering.py` | #55 |
| 8 | Jay | `jay/82-suspension` | `feat(admin): user suspension with reason codes and forced token refresh` | `services/admin-moderation/app/domain/suspension.py`, `tests/test_suspension.py` | #82 |
| 9 | Gaurang | `gaurang/73-dispute-form` | `feat(frontend): dispute form wired to the API, read-only after the window closes` | `frontend/src/features/disputes/` | #73 |
| 10 | Ayush | `ayush/notifications-api` | `feat(ws-gateway): notification history and unread count (GET /notifications)` | `services/ws-gateway/app/notifications.py`, `tests/test_notifications.py` | unticketed |

### Week 13

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 11 | Jaydip | `jaydip/66-refund` | `feat(payment): refund execution with fee treatment by fault` | `services/payment-escrow/app/domain/refund.py`, `tests/test_refund.py` | #66 |
| 12 | Jaydip | `jaydip/66-reconciliation` | `feat(payment): per-order ledger reconciliation against the invariants` | `services/payment-escrow/app/domain/reconcile.py`, `tests/test_reconcile.py` | #66 |
| 13 | Jay | `jay/84-adjudication-api` | `feat(dispute): admin adjudication with separate outcome and fault, idempotent` | `services/dispute/app/admin_api.py`, `tests/test_adjudication.py` | #84 |
| 14 | Jay | `jay/84-adjudication-console` | `feat(frontend): admin adjudication console with evidence and bid trace` | `frontend/src/features/admin-disputes/` | #84 |
| 15 | Jay | `jay/81-listing-queue` | `feat(admin): listing review and moderation queue (API and screen)` | `services/admin-moderation/app/domain/listing_review.py`, `frontend/src/features/admin-listings/`, `tests/test_listing_queue.py` | #81 |
| 16 | Harshal | `harshal/56-fraud-disputes` | `feat(dispute): fraud alerts open disputes with linked bid-trace evidence` | `services/dispute/app/adapters/fraud_consumer.py`, `services/fraud-detector/app/alerts.py`, `tests/test_fraud_dispute.py` | #56 |
| 17 | Harshal | `harshal/55-remeasure` | `docs(fraud): recall and precision after clustering` | `docs/fraud/v2-measurement.md` | #55 |
| 18 | Sagar | `sagar/47-search-api` | `feat(search): paginated search with category, price, status and sort filters` | `services/search-analytics/app/api.py`, `tests/test_search_api.py` | #47 |
| 19 | Sagar | `sagar/47-browse-wiring` | `feat(frontend): wire the browse screen to the search API` | `frontend/src/features/browse/` | #47 |
| 20 | Gaurang | `gaurang/74-notification-tray` | `feat(frontend): notification tray for outbid, KYC, dispute and payout events` | `frontend/src/features/notifications/` | #74 |
| 21 | Gaurang | `gaurang/75-seller-dashboard` | `feat(frontend): seller dashboard with escrow state and expected payout date` | `frontend/src/features/seller-dashboard/`, `services/search-analytics/app/dashboard.py` | #75 |
| 22 | Naitik | `naitik/25-sweep-lag` | `test(escrow-sweep): time-accelerated fixture proves release within 5 minutes` | `services/escrow-sweep/tests/test_sweep_lag.py` | #25 |
| 23 | Sumit | `sumit/113-week13-audit` | `docs(milestones): week-13 progress note, hours audit and feature freeze` | `docs/progress/week-13.md`, `docs/known-gaps.md` | #113 |

**Cross-owner commits:**
- 3 is in Jaydip's service, so Jaydip approves.
- 16 touches Jay's `dispute` service, so Jay approves.
- 19 and 21 cross between the frontend and search, so Gaurang and Sagar approve each other's work.

## Gate (#108)

- [ ] Every release trigger and both refund faults produce the correct ledger rows. No order is both released and refunded
- [ ] The sweep releases within 5 minutes. A dispute after the window closes gets `WINDOW_CLOSED`
- [ ] Fraud → auto-dispute with bid trace, and settlement blocked. Admin actions appear in the audit log
- [ ] Search, dashboard and tray work live. Week-13 note published and feature freeze declared → tag `plan-06`
