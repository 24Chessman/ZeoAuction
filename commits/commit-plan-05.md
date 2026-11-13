# Commit plan — Plan 5: Fraud Detection v1 & Mid-Semester Demo (weeks 10–11, Oct 5 – Oct 16)

**Status: committed 2026-10-22 on `project_repo/main` (16 commits, each authored by its member), together with the
KYC replacement and the frontend redesign (commits 16–21 below).** Done: commits 1–4
(fraud), 5 (demo seed: `infra/postgres/seed/demo-mid-sem.sql` + `scripts/demo-shill.py` instead of `demo-seed.sh`),
7 (runbook segment 4 updated), 9–12 (saga, failure injection, webhooks, pricing). The actual files differ a little from
the table: `app/signals/__init__.py` holds the signal mapping, `app/pipeline.py` and
`app/adapters/alert_producer.py` were added, and #64 needed no new `app/webhooks.py` because dedup was already in
`service.handle_webhook` (Plan 4), so commit 11 is `tests/test_webhooks.py` only. Saga progress lives in
`repository.py` (same transaction as the order), not a separate `saga_repo.py`; commit 9 also touches
`domain/orders.py` (O4a), `service.py`, `kafka_producer.py` and `docs/state-machines.md` §2. Commit 12 is
`tests/test_replayed_streams.py`: coverage was already 99%, and the replay kept the defaults.
**Not done:** 6 (environment checklist), 8 (demo feedback: needs the real evaluator notes), 13–15 (Plan 6
pull-forwards). **Milestone:** #107 *Fraud Detection v1 integrated* (Oct 9), Harshal tags `plan-05`.
**Mid-Semester Demo: Mon Oct 12.** Code freeze Thu Oct 8. After that, only fixes go in, on the `release/mid-sem` branch.

## Summary by member

| Member | Jira this plan | Commits | Focus |
|---|---|---|---|
| Harshal | #53, #54 (70 h, week 10) | 4 | Shill detector, fingerprint signals, alerts before close, v1 measurement |
| Jaydip | #63, #64 (30 h, week 11) | 3 | Saga compensations, failure injection, idempotent webhooks |
| Sagar | #45 (10 h, week 11) | 1 | Pricing coverage ≥ 80% and tuning |
| Sumit | demo lead | 2 | Demo seed script, demo runbook |
| Everyone | demo | – | Rehearsal fixes only after Oct 8 |
| Jay | pull-forward | 2 | Audit log live, dispute lifecycle spec (ahead of the 95 h in Plan 6) |
| Gaurang | pull-forward | 1 | Dispute form against the SDD contract |
| Ayush | demo support | 1 | Paid Render tier and demo environment checklist |

## Commits in merge order

### Week 10 — detector and demo preparation (freeze Oct 8)

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 1 | Harshal | `harshal/54-fingerprints` | `feat(fraud): device fingerprint overlap signals` | `services/fraud-detector/app/signals/fingerprint.py`, `tests/test_fingerprint.py` | #54 |
| 2 | Harshal | `harshal/53-shill-detector` | `feat(fraud): in-flight shill scoring over the per-auction window` | `services/fraud-detector/app/{scorer,signals/__init__}.py`, `tests/test_scorer.py` | #53 |
| 3 | Harshal | `harshal/53-alert-publisher` | `feat(fraud): publish ShillAlert v1, asserting it precedes auction close` | `services/fraud-detector/app/alerts.py`, `app/adapters/alert_repo.py`, `tests/test_alerts.py` | #53 |
| 4 | Harshal | `harshal/53-v1-measurement` | `docs(fraud): v1 recall and precision on dataset v1` | `docs/fraud/v1-measurement.md`, `services/fraud-detector/eval/quick_eval.py` | #53 |
| 5 | Sumit | `sumit/demo-seed` | `chore(demo): mid-semester demo seed with a verified seller, auctions and a shill ring` | `infra/postgres/seed/demo-mid-sem.sql`, `scripts/demo-seed.sh` | demo |
| 6 | Ayush | `ayush/demo-env` | `docs(infra): demo environment checklist and paid-tier switch-over` | `docs/demo/environment-checklist.md` | demo |
| 7 | Sumit | `sumit/demo-runbook` | `docs(demo): timed mid-semester runbook with presenter per segment and fallbacks` | `docs/demo/mid-semester-script.md` | demo |

After commit 7: cut the **`release/mid-sem`** branch and tag it `demo-mid-sem`. Rehearsal fixes are cherry-picked from `main`.

### Week 11 — demo (Oct 12), then settlement robustness

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 8 | Sumit | `sumit/demo-feedback` | `docs(demo): evaluator feedback and follow-up tickets` | `docs/demo/mid-semester-feedback.md` | demo |
| 9 | Jaydip | `jaydip/63-saga-compensation` | `feat(payment): saga coordinator with a compensating action per step` | `services/payment-escrow/app/domain/saga.py`, `app/adapters/saga_repo.py`, `tests/test_saga.py` | #63 |
| 10 | Jaydip | `jaydip/63-failure-injection` | `test(payment): failure injected at every saga step leaves no partial settlement` | `services/payment-escrow/tests/test_saga_failure_injection.py` | #63 |
| 11 | Jaydip | `jaydip/64-webhooks` | `feat(payment): signed provider webhooks deduplicated by event id and idempotency key` | `services/payment-escrow/app/webhooks.py`, `tests/test_webhooks.py` | #64 |
| 12 | Sagar | `sagar/45-pricing-coverage` | `test(pricing): reach 80% coverage and tune against replayed bid streams` | `services/pricing/tests/`, `services/pricing/app/domain/increment.py` | #45 |
| 13 | Jay | `jay/83-audit-log` | `feat(admin): append-only audit log API and writers in kyc and admin` | `services/admin-moderation/app/{api,audit}.py`, `services/kyc/app/admin_api.py`, `tests/test_audit_log.py` | #83 (early) |
| 14 | Jay | `jay/84-dispute-spec` | `docs(dispute): dispute lifecycle specification` | `docs/state-machines.md` (§4), `docs/dispute-lifecycle.md` | #84 (early) |
| 15 | Gaurang | `gaurang/73-dispute-form-early` | `feat(frontend): window-gated dispute form against the SDD contract (mocked)` | `frontend/src/features/disputes/` | #73 (early) |

### Added 2026-10-20 — KYC replaced (ADR-0013) and the "Evening sale" redesign

Committed after 12. Commits 1–12 used the actual files listed in the status note; commit 3 also carries the
fraud-detector env in `docker-compose.yml`, and commit 9 the §2 saga rows in `docs/state-machines.md`.

| # | Member | Branch | Commit message | Files | Jira |
|---|---|---|---|---|---|
| 16 | Sagar | `sagar/adr-0013-aadhaar-kyc` | `docs(adr): Aadhaar Secure QR and live face match for seller KYC (ADR-0013)` | `docs/adr/0013-aadhaar-secure-qr-and-face-match.md`, `docs/adr/README.md`, `docs/state-machines.md` (§3), `contracts/errors/kyc-error-codes.yaml` | ADR-0013 |
| 17 | Sagar | `sagar/40-face-match` | `feat(kyc): face match with YuNet + SFace and head-turn liveness (#40)` | `services/kyc/app/domain/face.py`, `app/adapters/face_engine.py`, `scripts/fetch_face_models.py`, `tests/{test_face,test_face_engine}.py`, `requirements.txt`, `Dockerfile`, `.gitignore` | #40 |
| 18 | Sagar | `sagar/38-aadhaar-qr` | `feat(kyc): verify the Aadhaar Secure QR signature, then the live face check (#38, #40)` | `services/kyc/app/{api,service,settings,main}.py`, `app/domain/{aadhaar,submission,verification}.py`, `app/adapters/{qr_reader,kyc_repo}.py`, `app/certs/uidai_offline_publickey_2026.cer`, `scripts/synthetic_qr.py`, `tests/` (removes `test_submission_api.py`), `README.md`, `docs/design.md`, `infra/postgres/init/21-kyc-aadhaar.sql`, `pyproject.toml`, `docker-compose.yml` (kyc env) | #38, #40 |
| 19 | Jay | `jay/80-face-review` | `feat(kyc): admin review of close face matches with side-by-side photos (#80)` | `services/kyc/app/admin_api.py`, `tests/test_admin_queue.py`, `frontend/src/pages/admin/AdminKyc{Queue,Review}Page.tsx` | #80 |
| 20 | Gaurang | `gaurang/evening-sale` | `feat(frontend): Evening sale redesign of tokens, components and pages` | `frontend/{package.json,package-lock.json,tailwind.config.ts,public/favicon.svg}`, `src/styles/index.css`, `src/main.tsx`, `src/components/{ui,layout,auction}/`, `src/pages/{Landing,Auctions,AuctionDetail,Account}Page.tsx`, `src/pages/auth/`, `src/pages/seller/CreateAuctionPage.tsx` | – |
| 21 | Gaurang | `gaurang/72-aadhaar-kyc-ui` | `feat(frontend): Aadhaar QR upload and live face capture KYC flow (#72)` | `frontend/src/pages/seller/KycPage.tsx`, `src/components/kyc/` (adds `FaceCapture.tsx`), `src/lib/{api,errors.ts}`, `src/lib/mock/` (adds `aadhaarQr`, `qrDecoder`, `secureQrFixture`, `kyc.test`), `tsconfig.tsbuildinfo` | #72 |

**Cross-owner commits:**
- 16 edits the shared state-machine doc, so Sumit approves. 19 touches Sagar's `kyc` service, so Sagar approves.
- 13 touches Sagar's `kyc` service, so Sagar approves.
- 14 edits the shared state-machine doc, so Sumit approves.

## Gate (#107 and the demo)

- [ ] Detector consumes the live `bid.events` and alerts before close. v1 recall and precision recorded
- [ ] Stopping the detector doesn't affect bidding, and it catches up from its offset
- [ ] Demo delivered Oct 12. Feedback logged as tickets
- [ ] Failure at each saga step leaves no partial settlement. A duplicate webhook has exactly one effect. Pricing ≥ 80% coverage → tag `plan-05`
