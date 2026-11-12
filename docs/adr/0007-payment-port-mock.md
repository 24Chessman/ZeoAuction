# ADR-0007: Payment behind a port with a mock adapter

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.7, ratified in Plan 7, #68) |
| **Date** | 2026-11-02 |
| **Owner** | Jaydip |
| **Deciders** | Jaydip, Ayush, Sumit |
| **Requirements** | FR-PAY-1, FR-PAY-6; SDD §2.6.7; services/payment-escrow/app/payment_port/port.py |

## Context

Testing financial escrow flows (checkout, capture, retry backoff, circuit breaking, refunds, reversals)
against live third-party gateway sandboxes introduces external latency, requires secret credentials in CI,
and is vulnerable to sandbox downtime or rate limits.
Additionally, the platform's academic mandate requires that no real money ever moves and that
every order view explicitly alerts users of test-mode simulation.

## Options considered

1. **Direct HTTP calls to Razorpay test-mode API**: difficult to test edge failure scenarios (e.g. simulating gateway 502s or signature corruption) deterministically.
2. **HTTP recording / mocking libraries (e.g. VCR.py)**: brittle to endpoint or payload changes and couples unit tests to external schema quirks.
3. **Hexagonal Architecture (Port & Adapters)**: define a clean domain `PaymentPort` protocol; implement `RazorpayPaymentAdapter` for hosted test-mode runs and `MockPaymentAdapter` for instant, deterministic, in-memory testing.

## Decision

**Option 3: Hexagonal `PaymentPort` with a deterministic `MockPaymentAdapter`.**
1. The domain interacts exclusively with `PaymentPort` protocol:
   - `create_checkout(order_id, amount, currency)`
   - `verify_checkout(provider_order_id, payment_id, signature)`
   - `capture(payment_id, amount, idempotency_key)`
   - `refund(payment_id, amount, idempotency_key)`
2. `MockPaymentAdapter`:
   - Runs in-memory with zero network I/O.
   - Generates predictable mock signatures (`simulated_payment`) allowing automated test clients to complete Checkout.
   - Supports failure simulation (`fail_next_capture`, `fail_next_refund`) to test retries, circuit breakers, and compensation paths.
3. `RazorpayPaymentAdapter`:
   - Used in hosted environments with Razorpay test keys (`rzp_test_...`).
4. Every response view returns `test_mode: True` and notice:
   `"Test mode: escrow is a simulation and no real money moves."`

## Consequences

- **Hermetic CI**: Entire test suite executes in seconds without credentials or internet access.
- **Fault injection**: Complex failure scenarios (e.g. S2 capture failure -> retry backoff -> breaker trip -> compensation) are tested with 100% reproducible fixtures.
- **Provider neutrality**: Switching or augmenting gateways requires only authoring a new adapter.

## Evidence

- `services/payment-escrow/tests/` passes 100% of unit tests against `MockPaymentAdapter`.
- Live test mode verified on Render blueprint using Razorpay credentials.
