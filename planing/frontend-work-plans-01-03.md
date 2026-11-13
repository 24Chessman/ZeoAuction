# Frontend work owed for Plans 1–3

Written 2026-10-05, after `frontend/` was removed from the repository. Sources: `plan-01`, `plan-02`, `plan-03`,
`README.md` (hours table and SDD gaps) and `commits/commit-plan-0{1,2,3}.md`.

Nothing in the repository counts as done for this work any more. The Plan 1–2 frontend that was built before
(149 Vitest tests) was deleted, so all of it has to be built again. The backend these screens call is already
implemented.

## Summary

| Plan | Jira | Work | Owner | Hours |
|---|---|---|---|---|
| 1 | – | React 18 + Vite + Tailwind scaffold, routing shell, API client | Gaurang | unticketed |
| 2 | #78 | Design tokens + shared component library | Jay | 25 |
| 2 | #79 | Login, registration and profile screens | Jay | 20 |
| 3 | #69 | Auction detail + bid form | Gaurang | 30 |
| 3 | #70 | Live price + flat-fee disclosure | Gaurang | 20 |
| 3 | #71 | WebSocket client: reconnect + optimistic updates | Gaurang | 30 |
| 3 | #72 | KYC document upload flow | Gaurang | 20 |
| 3 | #80 (UI part) | Admin KYC review queue + document viewer | Jay | part of 20 |
| 3 | – | Seller "create auction" screen (README gaps table: "Plans 3 and 6") | Gaurang | unticketed |

**Totals in Jira hours:**
- Ticketed: **145 h**. Plan 2 is 45 h (Jay) and Plan 3 is 100 h (Gaurang).
- #80 adds up to **20 h**. The backend half of #80 is already done in `services/kyc`, so only the UI part is left.
- Realistic range: **about 145–165 h**, plus the unticketed scaffold and the create-auction screen.

**By person:** Gaurang ~100 h plus the scaffold. Jay ~45 h plus the #80 UI.

**Schedule:** Plan 3 was due Sep 18, so all of this work is now late. Plan 4 has no frontend work, so Jay and
Gaurang have 0 h booked in weeks 8–9. Gaurang is free until Plan 6 (70 h) and Jay until Plan 6 (95 h). Doing the
work now doesn't overlap with either person's other booked hours.

## Plan 1: setup (pull-forward, no ticket)

- Scaffold React 18 + Vite + TypeScript + Tailwind (colors etc. come only from design tokens) + Vitest, with an
  app shell, routing shell and API client (`src/lib/api/`).
- Mock mode by default (`VITE_USE_MOCKS=true`) so screens can be built without the stack running.
- Add back the CI `frontend` job (lint, typecheck, coverage ≥ 80%, build), the `/frontend/` CODEOWNERS line and
  the `.gitignore` entries (`node_modules/`, `frontend/dist/`, `frontend/coverage/`).

## Plan 2: Bid Service MVP

- **#78 Tokens + component library (Jay, 25 h)**: the token set from SDD Fig. 8.1 (colors pre-checked for
  4.5:1 contrast, spacing, type). Primitives: button, input, card, badge/status pill, modal, toast, table, file-drop,
  banner. Every later screen is built from these.
- **#79 Auth screens (Jay, 20 h)**: login, registration and profile, built from the component library.
  Registration collects no KYC documents and shows the escrow-simulation notice (SDD §8.9).
- **Pull-forward for Gaurang**: start #69 (bid screen against mocked bid responses) and a #71 WebSocket spike
  against a mock server. These are counted under Plan 3.
- **Plan 2 definition of done (#104):** register → login → refresh → `/users/me` works end to end, and the auth
  screens use the component library.

## Plan 3: Identity & Real-Time

- **#69 Auction detail + bid form (30 h)**: client validation matches the rejection taxonomy
  (`contracts/errors/`, v1.0.0) exactly. The client never invents a rule the server doesn't enforce, and the
  reverse is true too.
- **#70 Live price + fee disclosure (20 h)**: the flat fee and the resulting total come from `GET /fees/quote`
  (currently a stub in payment-escrow) and are shown **before** a bid is placed (AC-07). Money is in integer cents
  on the client and two-decimal strings at the API boundary.
- **#71 WebSocket client (30 h)**: the price updates on submit and is reconciled when the server acknowledges the
  bid. Frames with a `server_seq` no greater than the last one seen are discarded. On reconnect the client
  re-subscribes with its last `server_seq` and applies the server's snapshot. A visible reconnect banner replaces
  a price that would otherwise freeze silently. Handle the gateway close codes in
  `services/ws-gateway/app/connections.py`: 4401 token expired, 4408 idle, 4429 rate limited, 1013 try again later.
  Also handle `TOKEN_STALE` forced refresh.
- **#72 KYC upload (20 h)**: a status strip that follows the state machine (SUBMITTED → UNDER_REVIEW →
  VERIFIED / REJECTED / SUSPENDED), the rejection reason shown inline with upload re-enabled, and a "why can't I
  list yet" panel that names the exact API refusal (`SELLER_NOT_VERIFIED`) (SDD Fig. 8.4).
- **#80 Admin KYC queue UI (Jay)**: queue view, approve and reject (a reason code is required), and a document
  viewer that uses signed URLs (SDD Fig. 8.8). Opening a document is audited by the backend.
- **Priority if time runs short** (from plan 3): #70 → #69 → #71 → #72.
- **Plan 3 definition of done (#105) items that need the UI:**
  - [ ] Two browsers watching one auction both see price updates live, and the outbid user gets an alert
  - [ ] Killing and restoring the network shows the reconnect banner, then resumes with no missed price
  - [ ] The bid screen shows the flat fee and total before placing a bid
  - [ ] Seller submits KYC → admin approves → token refreshes → seller creates an auction (can be shown via
        the API, but the demo expects screens)

## Commits to replay (from `commits/commit-plan-0{1,2,3}.md`)

| Plan | Branch | Commit |
|---|---|---|
| 2 | `gaurang/frontend-scaffold` | `feat(frontend): scaffold React 18 + Vite + Tailwind app shell and API client` |
| 2 | `jay/78-design-tokens` | `feat(frontend): design tokens with contrast-checked palette` |
| 2 | `jay/78-component-library` | `feat(frontend): shared component library primitives` |
| 2 | `gaurang/69-bid-screen-mock` | `feat(frontend): auction detail and bid form against the mocked bid contract` |
| 2 | `jay/79-auth-screens` | `feat(frontend): login, registration and profile screens` |
| 2 | `gaurang/71-ws-spike` | `feat(frontend): WebSocket client spike against a mock server` |
| 3 | `gaurang/69-bid-screen` | `feat(frontend): auction detail and bid form with contract-mirrored validation` |
| 3 | `gaurang/70-fee-disclosure` | `feat(frontend): live price with pre-bid flat-fee disclosure from /fees/quote (stub)` |
| 3 | `jay/80-kyc-queue-ui` | `feat(frontend): admin KYC review queue and document viewer` |
| 3 | `gaurang/71-ws-client` | `feat(frontend): WebSocket client with reconnect banner and optimistic updates` |
| 3 | `gaurang/72-kyc-upload` | `feat(frontend): KYC upload flow with verification status strip` |
