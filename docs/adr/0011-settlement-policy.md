# ADR-0011: Settlement policy numbers

| | |
|---|---|
| **Status** | **Proposed**: must be Accepted before any settlement code is written (end of Plan 1) |
| **Date** | 2026-08-14 |
| **Owners** | Jaydip (Payment), Sumit (Orchestration) |
| **Requirements** | FR-PAY-3, FR-PAY-9, FR-AO-4, FR-DISP-1, AC-07, AC-09, AC-12; SDD 1.3, Table 6.3; proposal §5 |

## Context

The proposal fixes the *rules* (a flat fee, escrow hold, a protection window, and fee treatment by fault) but not the *numbers*.
SDD §1.3 requires a fee configuration singleton that is fixed before any settlement code exists, so the fee shown before a bid,
the invoice, and the settlement can never disagree.

## Proposed decision

The numbers live in [`config/settlement-policy.yaml`](../../config/settlement-policy.yaml) and are seeded into
`payment.fee_config` as `fee_version = 2026-08-v1`. A contract test keeps the two in sync.

| Setting | Value | Note |
|---|---|---|
| Convenience fee | **25.00 flat per completed sale** | Not a percentage. Matches the SDD's fee-quote example. Losing bidders are never charged |
| Currency | USD | Follows ADR-0009; INR if Razorpay |
| Protection window | **7 days**, from when the seller marks the item shipped | Proposal default |
| Sweep cadence | Every 60 s; alert if lag exceeds 300 s | AC-12: release within 5 minutes |
| Fee on refund | BUYER fault: retain · SELLER or PLATFORM fault: refund in full | SDD Table 6.3 |
| Anti-snipe guard interval | 120 s | A bid in the final 2 minutes extends the auction |
| Extension length | 120 s | |
| Maximum extensions | 10 | Caps a bidding war at +20 minutes |

## Consequences

- To change the fee, insert a new `fee_config` row with a new `fee_version` and activate it. Existing
  orders keep the version they were invoiced with, so history stays reconcilable.
- The anti-snipe values are copied onto each auction when it's published, so changing policy never changes a live auction's rules.
- Ledger sign convention and invariants: see `infra/postgres/init/60-payment.sql` and `docs/state-machines.md` §2.
