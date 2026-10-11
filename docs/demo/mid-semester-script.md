# Mid-semester demo script — Mon Oct 12

| | |
|---|---|
| **Length** | 20 minutes + 5 minutes questions |
| **Rehearsal owner** | Sumit (proposed; confirm at the Sunday sync) · **Stack owner** Ayush |
| **Content** | Plan 5's required segments: one end-to-end auction from KYC-gated listing through bid to settlement with the fee in escrow, the fraud detector, and a code walkthrough |
| **Status** | **Draft.** Every step marked ⚠ hasn't been run on the Compose stack yet; the first rehearsal must clear them |

## Before the demo (T − 60 min)

```bash
docker compose down -v && docker compose up -d --build     # fresh DB: 32-, 51-, 61- SQL applied
docker compose ps                                          # every service healthy
MSYS_NO_PATHCONV=1 docker compose exec -T postgres psql -U postgres -d zeoauction -v ON_ERROR_STOP=1 -f /seed/dev-seed.sql
MSYS_NO_PATHCONV=1 docker compose exec -T postgres psql -U postgres -d zeoauction -f /verify/verify-guards.sql
cd frontend && cp .env.example .env.local                # then set VITE_USE_MOCKS=false to use the stack
npm run dev
```

Open tabs: the SPA (three browser profiles: seller, buyer1, buyer2), admin in a private window, `localhost:8006/api/v1/docs`
(payment), a terminal on `docker compose logs -f payment-escrow auction-orchestrator`.

Logins (password `zeo-dev-password`): `seller@zeo.local` (verified), `unverified@zeo.local`, `buyer1@zeo.local`,
`buyer2@zeo.local`, `admin@zeo.local`.

**Fallback.** If the stack misbehaves, switch to `VITE_USE_MOCKS=true`. The in-browser simulation covers segments 1–3
with the same screens: log in as `buyer2@zeo.local` to pay the closed tea-set auction. Say that it's the simulation.
Last resort: the recorded video.

## Segments

| # | Time | Presenter | What to show | Say |
|---|---|---|---|---|
| 0 | 1 min | Sumit | Architecture slide: 13 deployables, sync vs async boundaries | "Each service owns one schema; money moves only in Payment." |
| 1a | 3 min | Sagar | `unverified@zeo.local` tries to create an auction → refused. KYC upload → admin approves in the queue → the seller's token refreshes → listing allowed | The listing gate reads the JWT claim; approval bumps `token_version` (ADR-0005) |
| 1b | | Jay | Admin queue; mention every action lands in `admin.audit_log` (append-only) | `zeo_common.audit` writes in the action's transaction |
| 2 | 5 min | Naitik, Ayush, Gaurang | buyer1 and buyer2 bid on the seeded camera. The live price moves over WebSocket, buyer1 sees the outbid alert, and the fee (₹99.00) is shown before bidding ⚠ | `server_seq` decides order, never timestamps; replay gives the same winner (AC-04) |
| 2b | | Sagar | `curl localhost:8005/api/v1/pricing/<id>/velocity` while bidding: velocity rises, increment grows, `hot` flips ⚠ | Increment never drops below the tier floor, so replay still holds |
| 2c | optional | Naitik | Anti-snipe: a bid in the last 2 minutes extends the close (needs an auction closing during the demo) ⚠ | |
| 3 | 5 min | Sumit, Jaydip | The auction closes → order INVOICED (winning bid + ₹99.00) → winner clicks **Pay now** → (mock) Checkout → AUTHORIZED → CAPTURED → **IN_ESCROW**. Then `GET /orders/{id}/ledger` as admin: CAPTURE, HOLD, FEE_RETAIN ⚠ | Test mode, no real money, escrow is a simulation. The loser has no invoice (AC-09). The ledger is append-only, and a second RELEASE is rejected by the database |
| 3b | 1 min | Jaydip | `docker compose stop payment-escrow` during capture → order parks in `AWAITING_CAPTURE_RETRY` → start it → it recovers ⚠ | Deferred, never abandoned |
| 4 | 2 min | Harshal | Replay the labelled dataset into `bid.events` (`python -m dataset.replay ... --shift-to-now`). `/metrics` on :8011 shows the consumer reading it in order; restart → no re-read ⚠ | The scorer that turns features into alerts is Plan 5 (#55). Say it's **not built yet**, rather than implying an alert |
| 5 | 3 min | Naitik, Jaydip, Sumit | Code walkthrough: `bid/app/domain/conflict.py` (CAS + replay), `docs/state-machines.md` §1–2, `payment-escrow/app/domain/ledger.py` + `61-payment-razorpay.sql` guards | |
| – | 5 min | all | Questions. Log evaluator feedback as Jira tickets the same day | |

## Rehearsal checklist

- [ ] Rehearsal 1 (Sat Oct 10): full run on the stack, timed. Record every ⚠ that fails and its owner.
- [ ] Fixes merged to `demo/mid-sem` only; no features.
- [ ] Rehearsal 2 (Sun Oct 11): clean run under 20 minutes, fallback switch practised once.
- [ ] Recorded video of rehearsal 2 saved as the last-resort fallback.
- [ ] Demo machine: Docker Desktop with ≥ 6 GB RAM, stack built the night before, laptop on mains power.
