# Status toward Progress Report 3 (week-13 checkpoint #113, Oct 30)

As of **2026-10-06**, week 10. Plan 5 is running and the mid-semester demo is on **Mon Oct 12**. Progress Report 3 is the
week-13 written progress note and hours audit (#113, owner Sumit). It is due **Fri Oct 30**, which is also feature
freeze. By then Plans 1–6 are meant to be complete.

Sources: `planing/plan-0{1..6}-*.md`, the code in `services/` and `frontend/`, and the test suites.
- **Done** means the code is in the working tree and its tests pass.
- **Partial** means some of the ticket's scope exists.
- **Not started** means only the template skeleton, a schema file, or nothing exists.

Hours are the Jira estimates.

Caveats that apply to everything below:
- **Nothing is committed to git yet.** All work is untracked, so none of it is backed up or reviewable as PRs.
- **Nothing has been verified on the real stack.** Repositories are tested against fakes of asyncpg. The Docker
  checks (`verify-db`, `smoke-kafka`) and the end-to-end flows on PostgreSQL, Kafka and SeaweedFS haven't been run.
  None of the milestones (#104, #105) can be signed off until they are.
- **Progress notes #111 (week 5) and #112 (week 9) were never written.** There is no `docs/progress/` folder.
- **ADR-0009 (payment provider), ADR-0010 (third-party) and ADR-0011 (settlement policy) are still Proposed.** Plan 4
  says ADR-0009 and ADR-0011 must be Accepted before any settlement code is written.

---

## 1. Backend

### Done

| Plan | Tickets | Hours |
|---|---|---|
| 1 Setup | Monorepo, per-service schemas with GRANT ownership, frozen contracts, CI, `zeo-common` template, ADR drafts | ~82 |
| 2 Bid Service MVP | #19 bid validation, #20 conflict resolution, #29 Kafka producer, #30 Redis buffer + flusher, #31 idempotency, #51 fraud dataset, #90 CI, #91 JWT; auth-user endpoints and the auction-orchestrator core (unticketed) | ~168 |
| 3 Identity & real-time | #21 rejection taxonomy, #22 concurrency harness, #24 lifecycle guards, #32 anti-snipe, #38–#41 KYC (submission, signed-URL store, state machine, listing gate), #59 PaymentPort + mock adapter, #80 admin KYC queue API, #92–#94 ws-gateway, #95 gating middleware, #96 object storage | ~245 |
| **Total** | | **~495 h** |

Evidence: about 700 Python tests pass, ruff is clean, and coverage is at least 80% per service. Code size by service:

| Service | App lines | Tests |
|---|---|---|
| bid | 1,597 | 106 |
| auction-orchestrator | 1,287 | 79 |
| kyc | 1,244 | 58 |
| ws-gateway | 881 | 43 |
| auth-user | 750 | 32 |
| fraud-detector | 679 | 34 |
| bid-flusher | 497 | 19 |
| payment-escrow | 383 | 23 |

### Partial

| Ticket | What exists | What's missing |
|---|---|---|
| #61 Fee engine + disclosure API (Plan 4) | `GET /fees/quote` stub and `fees.py` (flat 25.00 from config) | Reading from `payment.fee_config`, versioning, use in invoicing |
| #53 Shill-bidding detector (Plan 5) | `fraud-detector/app/features.py` (bid velocity, inter-arrival gaps, coefficient of variation), pulled forward | The detector itself, scoring, recall and precision on the dataset, `shill.alerts` producer |
| #33 Settlement transition (Plan 4) | Guard A7 (`CLOSED → SETTLED`) in the lifecycle | The close → invoice → capture → escrow-hold saga |

### Left until Oct 30

**Plan 4: Pricing, payments and fees.** It was due Oct 2, so all of it is late.

| Ticket | Owner | Hours | Status |
|---|---|---|---|
| #33 Settlement transition | Sumit | 30 | Partial (guard only) |
| #34 Invoice with flat fee | Sumit | 25 | Not started |
| #42 Bid-velocity tracking | Sagar | 25 | Not started (pricing is a skeleton) |
| #43 Dynamic increment | Sagar | 30 | Not started |
| #44 Hot-auction flagging | Sagar | 20 | Not started |
| #60 Stripe/Razorpay test mode | Jaydip | 30 | Not started (blocked on ADR-0009) |
| #61 Fee engine + disclosure | Jaydip | 20 | Partial |
| #62 Escrow ledger + hold | Jaydip | 30 | Not started (schema `60-payment.sql` exists) |
| #52 Streaming consumer on `bid.events` | Harshal | 20 | Not started (the worker has health endpoints only) |
| #23 Tune conflict resolution against a load baseline | Naitik | 10 | Not started (harness exists, no baseline measured) |
| #106 milestone, #112 week-9 note | Jaydip, Sumit | – | Not done |

**Plan 5: Fraud v1 and mid-demo.** This is the current sprint.

| Ticket | Owner | Hours | Status |
|---|---|---|---|
| #53 Shill detector | Harshal | 45 | Partial (features only) |
| #54 Device-fingerprint signals | Harshal | 25 | Not started |
| #63 Saga coordination + compensation | Jaydip | 20 | Not started |
| #64 Provider webhooks with idempotency | Jaydip | 10 | Not started |
| #45 Pricing tests to 80% | Sagar | 10 | Not started |
| #107 milestone (Oct 9) | Harshal | – | Not done |

**Plan 6: Disputes, search and admin.** These tickets are backend work, except that #84, #81 and #82 each include an
admin screen.

| Ticket | Owner | Hours | Status |
|---|---|---|---|
| #83 Immutable audit log (build first) | Jay | 20 | Not started (admin-moderation is a skeleton) |
| #84 Dispute lifecycle + adjudication console | Jay | 35 | Not started (dispute is a skeleton) |
| #81 Listing moderation queue | Jay | 25 | Not started |
| #82 User suspension workflow | Jay | 15 | Not started |
| #65 Escrow release, all 3 triggers | Jaydip | 25 | Not started |
| #66 Refund + ledger reconciliation | Jaydip | 25 | Not started |
| #35 Release/refund terminal transitions | Sumit | 15 | Not started |
| #25 Protection-window timer + auto-release | Naitik | 25 | Not started (`escrow-sweep` logs "nothing released") |
| #97 Render cron for the escrow sweep | Ayush | 10 | Not started (not in `render.yaml`) |
| #55 Bid-ring clustering | Harshal | 30 | Not started |
| #56 Fraud-triggered disputes + evidence | Harshal | 20 | Not started |
| #46 Full-text search indexing | Sagar | 15 | Not started (search is a skeleton) |
| #47 Search + filter API | Sagar | 15 | Not started |
| Unticketed: `/admin/metrics/daily`, `/admin/broadcasts`, `/admin/audit-log`, `GET /notifications` | Jay, Ayush | – | Not started |
| #108 milestone, #113 week-13 note | Jay, Sumit | – | Due Oct 30 |

**Backend totals.**
- Done: about **495 h**.
- Left by Oct 30: about **600 h** of ticketed work. That is Plan 4 at about 230 h, Plan 5 at about 100 h and Plan 6
  at about 275 h, before counting the unticketed endpoints and the real-stack verification.
- Measured against the Plans 1–6 scope, the backend is **about 45% done**. Four services are still template
  skeletons: pricing, dispute, search-analytics and admin-moderation. escrow-sweep is a placeholder.

---

## 2. Frontend

The original frontend was deleted on 2026-10-05, and a new one was started the same day.

### Done (the new `frontend/`)

| Item | Plan / ticket | Notes |
|---|---|---|
| App scaffold: React 18 + Vite + TS + Tailwind + Vitest, mock mode | Plan 1 pull-forward | `npm run dev`, mock auth by default |
| Design tokens + visual system ("Security Print") | #78 (tokens part) | `tailwind.config.ts`, `DESIGN.md`, `.impeccable/design.json`; contrast is tested (WCAG AA) |
| Log in + Create account screens | #79 (2 of 3 screens) | They mirror the auth-user rules and error codes; the session restores itself with a rotating refresh token |
| Landing page | Not in the plans (extra) | Live demo auction, the four safeguards, how a sale settles |
| Tests | – | 45 tests, about 99% line coverage, TypeScript clean |

About **35 h** of planned work is done: the scaffold, most of #78's tokens, and two-thirds of #79. The landing page is
extra on top of that.

### Left until Oct 30

| Plan | Ticket | Owner | Hours | Status |
|---|---|---|---|---|
| 2 | #78 The rest of the component library: card, status pill, modal, toast, table, file-drop | Jay | ~15 | Partial (button, input, notice and form alert exist) |
| 2 | #79 Profile screen | Jay | ~5 | Not started |
| 3 | #69 Auction detail + bid form | Gaurang | 30 | Not started (a brief exists from the shape round) |
| 3 | #70 Live price + fee disclosure | Gaurang | 20 | Not started |
| 3 | #71 WebSocket client: reconnect + optimistic updates | Gaurang | 30 | Not started (ws-gateway backend is ready) |
| 3 | #72 KYC document upload flow | Gaurang | 20 | Not started (KYC backend is ready) |
| 3 | #80 Admin KYC review queue (UI half) | Jay | ~10 | Not started (API is ready) |
| 3 | Seller "create auction" screen | Gaurang | unticketed | Not started |
| 5 | Mid-demo screens: KYC → approve → list → bid → settle | Gaurang, Jay | – | Not started; **needed by Oct 12** |
| 6 | #73 Dispute form + evidence upload | Gaurang | 25 | Not started (dispute backend is not started either) |
| 6 | #74 Notification tray | Gaurang | 20 | Not started |
| 6 | #75 Seller dashboard | Gaurang | 25 | Not started |
| 6 | Admin screens inside #84 / #81 / #82: adjudication console, moderation queue, suspension | Jay | (in the backend hours) | Not started |
| 6 | Browse / search screen | Gaurang | unticketed | Not started (search API not started) |
| – | Restore the CI frontend job + CODEOWNERS line; add ESLint | Ayush, Gaurang | small | Not done |

**Frontend totals.**
- Done: about **35 h** of planned work, plus the landing page.
- Left by Oct 30: about **200 h** of ticketed screens. On top of that come the admin-console screens, the
  unticketed browse, create-auction and mid-demo screens, and the CI work.
- Measured against the Plans 1–6 scope, the frontend is **about 15% done**.
- The Plan 3 screens (#69–#72, 100 h) are the biggest block. They are also what the mid-semester demo needs.

---

## Biggest risks before Oct 30

1. **Mid-semester demo on Oct 12, six days away.** It needs KYC → listing → bid → settle with the fee into escrow.
   KYC and bidding work in the backend. Settlement (#33, #34), the escrow ledger (#62) and every demo screen do not
   exist yet.
2. **Plan 4 is entirely overdue.** About 230 h slipped past Oct 2, and Plan 6 has another 275 h of backend on top.
   The week-5 rule ("reassign if a member is more than 15% off plan") is being missed for Jaydip, Sagar and Gaurang.
3. **Blocked decisions.** ADR-0009 blocks #60, the currency and the fee display. ADR-0011 blocks settlement. Both need
   accepting this week.
4. **Nothing is committed to git and nothing is verified on the stack.** A disk failure would lose everything, and the
   milestones can't be signed off.
5. **The checkpoint notes are missing.** #111 and #112 were never written, and #113 is supposed to be the third in
   that series.

### Suggested order for the next three weeks
1. **This week, for the demo:**
   - Accept ADR-0009 and ADR-0011.
   - Commit the history (`commits/plan-01-commits.sh`, then Plans 2–3).
   - Build #33, #34 and #62 on the mock adapter.
   - Build the demo screens: #69 and #70 first, then #72, #80 UI and create-auction. Keep #71 as live updates.
2. **Weeks 11–12:**
   - Finish Plan 4: pricing #42–#44 and the #52 consumer.
   - Finish Plan 5: #53 detector, #63 saga.
   - Write the #111 and #112 notes retroactively.
3. **Weeks 12–13:**
   - Plan 6 backend in dependency order: #83 audit log, then disputes #84, then release/refund #65, #66, #35, #25,
     then search #46, #47.
   - Frontend #73–#75 and the admin screens.
   - Run the stack verification, then write #113.
