# ADR-0009: Payment provider — Stripe or Razorpay

| | |
|---|---|
| **Status** | **Proposed**: the team decides at the Plan 1 review (Aug 14) |
| **Date** | 2026-08-14 |
| **Owner** | Jaydip |
| **Requirements** | FR-PAY-1, FR-PAY-2, FR-PAY-7; SDD 5.2.1; proposal §6, §7, §11 |

## Context

The project documents disagree:

- **Proposal** (§6, §7, §11): *Razorpay test mode*. The case for it: Route transfers support a settlement hold
  with timed release and reversal, which map onto the escrow window, and it's INR-native.
- **SDD** (§5.2.1, `POST /webhooks/stripe`) and **Jira** #60/#64: *Stripe test mode with manual capture*.

Whichever we pick, ADR-0007 (already accepted) puts payment behind `PaymentPort` with a deterministic
`MockPaymentAdapter`. The provider is one adapter, not a dependency of the demo. So this choice affects exactly
one class, the webhook endpoint, and the currency, and nothing else.

## Options considered

1. **Stripe (test mode, manual capture)**
   - Pros: matches the SDD, the Jira tickets and the endpoint inventory, so no document changes are needed. Manual
     capture is the escrow primitive. The test mode and webhook tooling (CLI forwarding) are well documented.
   - Cons: USD-centric examples. Stripe accounts in India have onboarding restrictions (irrelevant in test mode).
2. **Razorpay (test mode, Route transfers)**
   - Pros: matches the submitted proposal. Transfer on-hold and reversal map directly onto escrow. INR-native.
   - Cons: we'd have to update the SDD, Jira #60/#64 and the webhook route name. Some of Route's test-mode behaviour
     needs activation on the account.

## Proposed decision

**Stripe test mode with manual capture**, currency **USD**, because the implementation documents (the SDD and Jira)
and every published contract already assume it. The proposal's Razorpay rationale is kept as the documented
alternative. Since both sit behind `PaymentPort`, switching later costs one adapter.

If the team chooses Razorpay instead:
- Rename `POST /api/v1/webhooks/stripe` to `/webhooks/razorpay` in the Plan 4 contract.
- Change `currency` to `INR` in `config/settlement-policy.yaml` and in the `fee_config` seed (the contract test keeps them in sync).
- Update Jira #60/#64.

## Consequences

- There is no real money anywhere: test keys only, synthetic accounts. It's stated in the UI and the user manual (NFR-SEC-4).
- `PAYMENT_ADAPTER=mock` stays the default locally and in CI, so no network access or keys are needed.
- Provider keys live only in Render environment groups.
