# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React 18 + Vite + TypeScript + Tailwind + Vitest, with a mock mode (`VITE_USE_MOCKS`) so screens can be built
before or without the running stack. Deployed on Vercel. The frontend is being rebuilt from scratch: as of
2026-10-05 there is no `frontend/` directory (see `planing/frontend-work-plans-01-03.md`).

## Users

Three roles, served with equal weight. None is secondary:

- **Buyers / bidders**: browse auctions, watch them live, bid, and react to outbid alerts.
- **Sellers**: must pass KYC before they can list. Then they create auctions, fulfil orders and get paid out of
  escrow.
- **Administrators**: review KYC submissions and documents, moderate, adjudicate disputes and read the audit log.

Third-party applications use the public REST API and have no UI.

## Product Purpose

ZeoAuction is a distributed, real-time auction platform built as microservices (M.Sc. IT semester-3 group project,
8 members, 2026-08-03 to 2026-11-20). Every role's end-to-end flow has to work in the browser against the real
services.

Demo milestones:
- **Mid-semester demo, 2026-10-12**: the UI shows the full flow: seller KYC → KYC-gated listing → live bidding →
  settlement, with the fee going into escrow.
- **Final demo, 2026-11-18**: the live deployment.

## Positioning

**Trust and safety first.** Every auction is backed by safeguards a generic auction site doesn't make visible:

- KYC-verified sellers
- escrow with a buyer-protection window
- fraud detection that runs during the auction
- a fee disclosed before bidding
- server-ordered bids
- anti-snipe extensions

Real-time bidding matters, but it comes second to the user's confidence that the auction is safe and fair.

## Operating Context

- Live data reaches the browser through the ws-gateway. Connections can drop and resume.
- Status labels follow the state machines in `docs/state-machines.md`: auction, order, KYC and dispute.
- Fee, protection-window and anti-snipe numbers come from `config/settlement-policy.yaml` (ADR-0011, still
  Proposed). Read them from there and never hard-code them.
- API and event contracts are frozen in `contracts/`. Error codes are in `contracts/errors/`.

## Capabilities and Constraints

- **The server is the authority.** The UI never invents a rule the server doesn't enforce, and never skips one it
  does. Error copy comes from the `contracts/errors/` taxonomy.
- **Bidder privacy.** Bidders appear only under nicknames, never real names. The reserve amount is never shown,
  only whether it has been met.
- **Simulation honesty** (a CLAUDE.md rule). Payments run in test mode and escrow is simulated. User-facing text
  where money appears says so.
- **Money** is a two-decimal string at the API boundary and integer cents in the frontend. Never a float.
- **Undecided:**
  - the payment provider and therefore the currency (ADR-0009)
  - third-party services (ADR-0010)
  - the settlement numbers (ADR-0011)
  - which screens beyond the Plans 1–3 work are needed, since the screen inventory is to be re-specified

## Evidence on Hand

- Proposal, SDD v1.0 and the Jira timeline are in `project_docs/`. Screen notes are in
  `docs/screen-descriptions.md`.
- Seeded development data: `infra/postgres/seed/dev-seed.sql`.
- There are no real users, customers, testimonials, reviews or performance results yet. Never fabricate them. Never
  show throughput or latency figures until the measured load tests exist.

## Product Principles

1. **Make safety visible at the moment it matters.** Show KYC status, the fee, escrow state and the protection
   window where they affect a decision.
2. **The server decides.** Show the server's order, states and error codes exactly. Never predict them or add to
   them.
3. **Every role gets a complete path.** Buyer, seller and admin flows are each finished end to end, not stubs
   around one hero flow.
4. **Protect people's identities.** Show nicknames instead of names, and whether the reserve is met instead of its
   amount.
5. **Never pretend.** It's a simulation and it says so. No invented metrics, reviews or users.

## Accessibility & Inclusion

The target is WCAG 2.1 AA (SDD NFR-USE-2).
