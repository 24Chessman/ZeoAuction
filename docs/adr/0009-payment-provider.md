# ADR-0009: Payment provider: Razorpay (test mode)

| | |
|---|---|
| **Status** | **Accepted** (2026-10-10, at the start of Plan 4 implementation); to be ratified with two approvals on the Plan 4 PR |
| **Date** | 2026-08-14 (proposed), 2026-10-10 (decided) |
| **Owner** | Jaydip |
| **Requirements** | FR-PAY-1, FR-PAY-2, FR-PAY-7; SDD 5.2.1; proposal §6, §7, §11 |

## Context

The project documents disagreed:

- **Proposal** (§6, §7, §11): *Razorpay test mode*. The case for it: Route transfers support a settlement hold
  with timed release and reversal, which map onto the escrow window, and it's INR-native.
- **SDD** (§5.2.1, `POST /webhooks/stripe`) and **Jira** #60/#64: *Stripe test mode with manual capture*.

ADR-0007 (already accepted) puts payment behind `PaymentPort` with a deterministic `MockPaymentAdapter`, so the
provider is one adapter, the webhook endpoint and the currency.

## Options considered

1. **Stripe (test mode, manual capture)**: matches the SDD and Jira wording, USD-centric, and Stripe accounts
   in India have onboarding restrictions.
2. **Razorpay (test mode, manual capture, Route for payouts)**: matches the submitted proposal, INR-native,
   and Route transfers map onto releasing escrow to sellers. It needs the buyer to pay in Razorpay Checkout.

## Decision

**Razorpay test mode, currency INR.** The proposal is what we submitted, the team is in India, and INR
removes a currency conversion from every demo.

### How the escrow primitives map onto Razorpay

| Port operation | Razorpay | Notes |
|---|---|---|
| `create_checkout` | `POST /v1/orders` with `payment_capture: 0` | The buyer pays in Checkout. The payment is **authorized**, not captured |
| `verify_checkout` | `HMAC-SHA256(key_secret, "{order_id}\|{payment_id}")` | The signature Checkout returns to the browser |
| `capture` (S2) | `POST /v1/payments/{id}/capture` | Manual capture into platform custody. A refused capture is resolved by reading the payment back (already `captured` means success, `failed` means a decline) |
| `refund` | `POST /v1/payments/{id}/refund` | Our idempotency key goes in `notes` and is looked up before creating |
| `payout` (release) | Route: `POST /v1/payments/{id}/transfers` to the seller's linked account | One demo linked account (`RAZORPAY_LINKED_ACCOUNT`) stands in for every seller until seller onboarding (Plan 6) |
| `verify_webhook` | `X-Razorpay-Signature` = `HMAC-SHA256(webhook_secret, raw body)` | `X-Razorpay-Event-Id` de-duplicates deliveries in `payment.provider_events` |

### Consequence for the order state machine

Stripe's "the server authorises a saved card at close" doesn't exist in Razorpay without recurring
mandates, so **the winner pays**: S1 opens the order and invoice (`INVOICED`), the winner opens Checkout
(`POST /orders/{id}/checkout`), and the authorisation arrives through Checkout's signed handler
(`POST /orders/{id}/payment`) or the `payment.authorized` webhook, whichever is first. The order then moves to
`AUTHORIZED` and is captured into escrow. An order not paid within `checkout.payment_window_hours` (48 h) is
compensated (O4). See `docs/state-machines.md`, section 2.

### What changed in the documents

- The webhook is `POST /api/v1/webhooks/razorpay` (`/webhooks/mock` locally), not `/webhooks/stripe`.
- `currency` is `INR` in `config/settlement-policy.yaml` and in the `fee_config` seed
  (`infra/postgres/init/61-payment-razorpay.sql`). The contract test keeps them in sync.
- Jira #60/#64 should be retitled from Stripe to Razorpay.

## Consequences

- No real money anywhere: the adapter **refuses any key that is not `rzp_test_...`**. Synthetic accounts only.
  This is stated in the UI, in every order view (`test_mode`, `notice`) and in the user manual (NFR-SEC-4).
- `PAYMENT_ADAPTER=mock` stays the default locally and in CI, so no network or keys are needed. The mock follows
  the same Checkout flow, so the demo can run offline.
- Keys live only in `.env` (git-ignored) locally and Render environment groups when hosted.
- A webhook needs a public URL. Locally, Checkout's signed handler is enough, and a tunnel is optional.
- Razorpay automatically refunds an authorisation that is never captured, so a compensated (cancelled) order
  leaves no money with the platform.
