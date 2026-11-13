# CLAUDE.md — ZeoAuction

Distributed real-time auction platform (microservices / SOA). M.Sc. IT semester-3 group project, 8 members,
16 weeks (Aug 3 – Nov 20, 2026). Development happens across the whole codebase, every service, not just
one member's slice. The old frontend was removed on 2026-10-05 and is being rebuilt from scratch in `frontend/`.

## Where the truth lives — read before changing things

| Need | Read |
|---|---|
| Services, ports, schemas, sync/async boundaries, data-ownership exceptions | `docs/architecture.md` |
| Rules every PR follows (commits, money, tests, data) | `docs/engineering-conventions.md` |
| Auction / order / KYC / dispute state machines | `docs/state-machines.md` |
| Frozen API + event contracts (code changes to match them, never the reverse) | `contracts/` + `contracts/README.md` |
| Fee, protection window, anti-snipe numbers | `config/settlement-policy.yaml` (ADR-0011) |
| What to build when, by whom | `planing/README.md` + `planing/plan-0N-*.md` |
| Who commits which files, in what order | `commits/commit-plan-0N.md` |
| Full design (SDD v1.0), proposal, Jira CSV | `project_docs/` (PDF/TeX/CSV) |
| Decisions | `docs/adr/` (0009 Razorpay and 0011 settlement policy Accepted 2026-10-10; 0010 third-party is still **Proposed**) |

## Current state (update this section as plans land)

- **Plan 1 (setup)**: implemented. **Plan 2 (Bid Service MVP)**: implemented in the working tree: bid, bid-flusher,
  auth-user, auction-orchestrator core, payment-escrow port, fraud-detector dataset.
- **Plan 3 (Identity & Real-Time)**: **backend** implemented in the working tree: `zeo_common.storage` (S3 SigV4,
  signed URLs) and `zeo_common.gateway` (listing gate, `TOKEN_STALE` forced refresh via `tv:{user_id}`); kyc
  (submission, document store, K1–K7, admin queue); auction-orchestrator (A1–A8 guards, listing gate, anti-snipe from
  `bid.events`, lifecycle timer, `auction.events` producer; schema change `31-auction-bid-tracking.sql`); bid (taxonomy
  v1.0.0, `tests/load/concurrency_harness.py`); ws-gateway (handshake, fan-out, outbid, coalescing); payment-escrow
  `GET /fees/quote` stub; fraud-detector `app/features.py` (#53 pull-forward).
  search-analytics, dispute and admin-moderation are still template skeletons.
  `commits/commit-plan-02.md` and `-03.md` still say "projected".
- **Plan 4 (Pricing, Payments & Fees)**: **payments and settlement** implemented in the working tree (2026-10-10).
  ADR-0009 = **Razorpay test mode, INR**; ADR-0011 fee = **₹99.00** (`fee_version 2026-10-v1`, `61-payment-razorpay.sql`).
  The winner pays in Razorpay Checkout: INVOICED → AUTHORIZED → CAPTURED → IN_ESCROW (new O1a, `docs/state-machines.md`).
  payment-escrow: `app/domain/{fees,orders,invoice,ledger}.py`, `PaymentPort` reworked for Checkout,
  `razorpay_adapter.py` (refuses non-`rzp_test_` keys), repository, `SettlementStep v1` producer, settlement worker
  (capture retries/breaker, resume, 48 h unpaid expiry), webhooks. Orchestrator: winner bidder/amount tracking
  (`32-auction-settlement.sql`), **CT-4** `POST /internal/orders` client behind a breaker, A7 on `HELD` from
  `payment.events`. Circuit breaker moved to `zeo_common.circuit_breaker`. Frontend: INR formatting, `SettlementPanel`
  (Pay now, Razorpay Checkout or a simulated one in mock mode). **Rest of Plan 4 also in the working tree** (2026-10-10):
  pricing engine (`services/pricing`: velocity from `bid.events`, dynamic increment on CT-3 cached at `inc:{id}` 60 s,
  hot flag; ladder in `51-pricing-dynamic.sql`, **whose base must equal bid's `INCREMENT_TIERS`**, the floor the AC-04
  replay relies on); bid CT-3 fallback never below that floor (`tests/test_ct3_breaker.py`), Compose bid uses
  `PRICING_MODE=http`; fraud consumer scaffold (`app/{consumer,windows}.py`); `tests/load/aggregate_rig.py` +
  `docs/perf/week-09-baseline.md` (indicative only; the knee is about 700 bids/s per event loop, so conflict.py was
  not tuned); `infra/loadtest/`; `zeo_common.audit`; `docs/dispute-lifecycle.md` (draft); `docs/progress/week-09.md`;
  `docs/demo/mid-semester-script.md`. Still open: #106 sign-off on the real stack, the host load run, and members'
  actual hours.
- **Plan 5 (Fraud v1, settlement robustness)**: engineering implemented in the working tree (2026-10-19).
  fraud-detector: all seven SDD 5.4.2 signals in `app/features.py` + `app/signals/` (#54 in-auction fingerprint
  overlap), `app/scorer.py` (`shill-v1`, threshold 0.6, `FRAUD_ALERT_THRESHOLD`), `app/alerts.py` (`ShillAlert v1` to
  `fraud.alerts`; `must_precede_close`: a late alert is stored as a miss, never published), `eval/quick_eval.py`.
  **v1 on dataset v1: recall 0.9025, precision 0.9325, 0 late** (`docs/fraud/v1-measurement.md`, with known limits:
  fast honest newcomers score 0.75, so live demos run at 0.8). payment-escrow #63: `app/domain/saga.py`,
  `payment.saga_steps` written with each step, S3 resumed by the worker, a definitive S3 failure compensates S2
  (O4a: full reversal + COMPENSATION rows, CANCELLED), `tests/test_saga_failure_injection.py`; worker passes now
  isolate per-order failures. #64: `tests/test_webhooks.py`. Pricing #45: `tests/test_replayed_streams.py`.
  Demo: `infra/postgres/seed/demo-mid-sem.sql` + `scripts/demo-shill.py`. The demo itself (Oct 12), the
  feedback tickets and the Plan 6 pull-forwards aren't covered.
- **KYC replaced (2026-10-20, uncommitted, ADR-0013 Proposed)**: document upload is gone. Sellers upload a **photo of
  the Aadhaar Secure QR** (`POST /kyc/aadhaar`, field `qr_image`, optional `mobile`). `app/adapters/qr_reader.py` reads it
  with **zxing-cpp**; `app/domain/aadhaar.py` turns the decimal text into bytes, inflates the GZip (bounded), checks UIDAI's
  RSA-SHA256 signature over all but the last 256 bytes against the bundled `app/certs/uidai_offline_publickey_2026.cer` (UIDAI key 06, valid to 2029)
  only, and parses the 0xFF fields (V2 layout and the 2019 one with mobile/email hashes); 18+; optional mobile check
  (last 4 digits in V2, hash in 2019). No QR age limit by default (`KYC_AADHAAR_MAX_AGE_HOURS=0`). Then a **live face check**
  (`POST /kyc/submissions/{id}/face`, 3-8 webcam frames; OpenCV YuNet + SFace in `app/adapters/face_engine.py`, decision +
  basic head-turn liveness in `app/domain/face.py`). Clear match (K3a) or close (K2) -> UNDER_REVIEW;
  an admin approves every seller (K3, since 2026-10-22), 3 failures -> REJECTED + 24 h cooldown (K4a). State names and the `kyc_status` mirror are unchanged. Schema
  `21-kyc-aadhaar.sql` (`qr_generated_at`); errors `contracts/errors/kyc-error-codes.yaml` v2.0.0. Models are not committed:
  `python services/kyc/scripts/fetch_face_models.py` (Dockerfile does it). Synthetic signed QR PNGs for tests/demos:
  `services/kyc/scripts/synthetic_qr.py` + dev cert via `KYC_EXTRA_TRUSTED_CERTS` (never hosted). Frontend: `KycPage`
  (2 steps: QR photo with preview, then camera), `components/kyc/FaceCapture.tsx`, admin side-by-side photo compare;
  mock mode scripts outcomes by the QR file name (`tampered`, `noqr`, `review`, `nomatch`), mock state is v4. Not yet
  tried: a real Aadhaar QR (QRs signed before Feb 2026 may need an older UIDAI certificate via `KYC_EXTRA_TRUSTED_CERTS`), and face thresholds
  on real faces (only OpenCV sample images).
- **2026-10-22 (uncommitted)**: (1) every seller needs an admin's approval: a clear face match (`faceMatch`, K3a) now goes
  SUBMITTED -> UNDER_REVIEW like K2, and only K3 `approve` verifies. (2) **Listing photos**: orchestrator
  `POST/DELETE /auctions/{id}/images` (`app/domain/images.py`, ≤ 6 JPEG/PNG/WebP ≤ 5 MB, DRAFT/SCHEDULED only, bucket
  `listing-images`, schema `33-auction-images.sql`), `images` on every auction view; frontend `PhotoPicker` on the create
  page (uploads after the draft is created, retries reuse the draft), seller photos replace stock ones in `AuctionArt`,
  gallery on the detail page, mock routes too.
- Plans 1–3 are committed on `main` (2 commits); Plan 4 is committed on branch `plan_4`; Plan 5 is uncommitted. `commits/plan-01-commits.sh` replays
  Plan 1 as per-member commits; `commits/commit-plan-04.md` maps the Plan 4 files to members.
- As of 2026-10-20 every suite passes: ruff clean, 1,163 Python tests, 62 frontend tests (typecheck + eslint clean). The Docker stack checks
  (`verify-db`, `smoke-kafka`), the new SQL (`32-`, `51-`, `61-`) and the Plan 3–4 flows against real
  PostgreSQL/Kafka/SeaweedFS/Razorpay haven't been run in this environment yet (repositories are tested against
  recording fakes of asyncpg; the Razorpay adapter against a scripted `httpx.MockTransport`).

## Layout

- `services/<name>/`: 13 deployables (10 APIs, workers `fraud-detector` + `bid-flusher`, cron `escrow-sweep`).
  Inside each: `app/api.py` routes · `app/domain/` pure logic (no I/O) · `app/adapters/` Redis/Kafka/PG/HTTP ·
  `app/settings.py` · `tests/`. **Every service's package is named `app`**, so suites must run in separate pytest processes.
- `libs/zeo-common/`: shared template. Create services with `zeo_common.create_app(name, version=...)` (gives
  `/healthz`, `/readyz`, `/metrics`, request IDs, JSON logs, error envelope, docs at `/api/v1/docs`).
- `infra/postgres/init/NN-<schema>.sql`: one schema + one login role per service, GRANT-enforced.
  `infra/kafka/` topics + Render image. `infra/s3/` SeaweedFS buckets.
- `frontend/`: React 18 + Vite + TS + Tailwind (color tokens in `src/styles/index.css`, light + dark) + Vitest.
  Rebuilt 2026-10-06 for Plans 1–3: landing, auth, profile, browse, auction detail + bid panel (fee from
  `/fees/quote`), WebSocket client (`src/lib/live/LiveClient.ts`), KYC (Aadhaar e-KYC + face check since 2026-10-20), admin KYC queue, create auction.
  `VITE_USE_MOCKS=true` (default) runs an in-browser simulation of the services (`src/lib/mock/`, including
  orders; log in as `buyer2@zeo.local` (tea set) or `buyer1@zeo.local` (necklace) to pay a closed auction). With
  `rzp_test_` keys in the root `.env`, `npm run dev` opens **real Razorpay test Checkout** in mock mode through the
  dev-server bridge `dev/razorpayBridge.ts` (secret stays in Node, never bundled); without keys Checkout is simulated.
  Plan 4 UI (2026-10-10): settlement progress, test-card hints, admin escrow ledger, Orders on `/account`. Listing
  photos are Pexels stock photos (`src/lib/photos.ts`, credits there; `public/images/auctions/`). `.env.example`
  points it at the real stack. Settlement numbers are read from `config/settlement-policy.yaml` at build time.
  The old "Security Print" design (`DESIGN.md`, `.impeccable/`) no longer describes the frontend. Current look (2026-10-20):
  "Evening sale": midnight ink + persimmon brand, emerald/cobalt/saffron accents, Bricolage Grotesque display +
  Plus Jakarta Sans text, `.bg-midnight` bands, rounded-3xl/4xl panels, soft `shadow-lift`/`shadow-float`.
- `tests/contracts/`: validates OpenAPI/event schemas, and checks that topics and the fee config stay in sync with infra.

## Commands (Windows: no `make`, so run the Makefile recipe directly)

```bash
# Python (venv already exists at .venv; local Python is 3.14, but code must stay 3.11-compatible)
.venv/Scripts/python.exe -m ruff check .
PYTHON="$PWD/.venv/Scripts/python.exe" sh scripts/test-all.sh     # zeo-common + contracts + every service
cd services/<name> && ../../.venv/Scripts/python.exe -m pytest -q  # one service

# Frontend
cd frontend && npm run typecheck && npx vitest run && npm run dev

# Stack (Docker Desktop must be running; ~6 GB RAM)
docker compose up -d --build && docker compose ps
docker compose exec -T postgres psql -U postgres -d zeoauction -v ON_ERROR_STOP=1 -f /seed/dev-seed.sql
docker compose exec -T postgres psql -U postgres -d zeoauction -f /verify/verify-guards.sql
docker compose down -v   # reset (schema changes only apply to a fresh DB)
```
In Git Bash, prefix `docker compose exec` that passes container paths with `MSYS_NO_PATHCONV=1`.
If the parallel build crashes Docker Desktop, build services one at a time.
Seeded login: `buyer1@zeo.local` / `zeo-dev-password`.

## Non-negotiable rules

- **Money**: two-decimal string at every boundary (`"1250.00"`), `Decimal` inside. Never a float.
  Use `zeo_common.parse_money` / `format_money`.
- **Errors**: `raise ApiError(code, message, status)`. Never an ad-hoc error body. Codes come from `contracts/errors/`.
- Routes under `/api/v1`. Bid- and money-moving endpoints take `Idempotency-Key`.
- Kafka events carry `event_id` + `schema_version`. Keys come from `contracts/events/topics.yaml` (`bid.events` keyed
  by `auction_id`). Ordering comes from `server_seq`, never from timestamps.
- A service touches **only its own schema**. No cross-schema FKs. Append-only tables (`payment.escrow_ledger`,
  `admin.audit_log`, `kyc.kyc_state_transitions`, `auction.auction_state_transitions`) are never updated. Correct them with a new row.
- Schema changes go in a **new** numbered SQL file next to the owner's (e.g. `41-...sql`). Never edit a file others build on.
- UTC timezone-aware timestamps. Coverage ≥ 80% per service. Ruff must be clean (config in root `pyproject.toml`).
- Payments are **test mode only** (Razorpay `rzp_test_` keys, enforced by the adapter). Escrow is a simulation, so say
  so in user-facing text. No secrets in the repo: Razorpay keys go in `.env` (git-ignored) or Render env groups.
- Commits: Conventional Commits with the Jira id, e.g. `feat(bid): validate auction-open (#19)`. Branches
  `<member>/<jira-id>-<topic>`. Each file belongs to the member listed in `commits/commit-plan-0N.md`.
