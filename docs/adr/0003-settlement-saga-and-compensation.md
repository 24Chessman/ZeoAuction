# ADR-0003: Saga with compensations for settlement

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.3, ratified in Plan 7, #37, #68) |
| **Date** | 2026-11-02 |
| **Owner** | Jaydip |
| **Deciders** | Sumit, Jaydip, Ayush |
| **Requirements** | FR-PAY-1, FR-PAY-3, AC-08; SDD §2.6.3, §5.2.3; docs/state-machines.md (O1-O5) |

## Context

Settling an auction when the hammer falls involves multiple independent subsystems:
Auction Orchestrator (closed with winner), Payment Gateway (Razorpay authorization and capture),
Escrow Ledger (custody hold and fee allocation), and Notification service.
A synchronous distributed transaction (2PC) is impossible across external HTTP APIs and Kafka.
If any step fails (e.g. buyer card capture declines, network drops between S2 and S3),
the system must either retry safely or compensate backwards to ensure no phantom custody
or partial billing occurs.

## Options considered

1. **Two-phase commit (2PC)**: requires coordination across external payment gateway and Kafka; introduces blocking locks and high latency.
2. **Best-effort writes without state tracking**: prone to silent custody drift, uncaptured authorizations, and orphaned invoices.
3. **Choreographed / orchestrated Saga with compensating transactions**: explicit step records (`saga_steps`), strict idempotency keys (`order:{id}:{operation}`), forward retries for transient errors, and backward compensation (O4 void invoice, O4a reverse capture) for definitive failures.

## Decision

**Option 3: Saga with compensations.**
The settlement lifecycle follows four distinct steps (S1-S4):
- **S1 (open_order)**: Invoices winning bidder for `winning_bid + fee` (`INVOICED`).
- **S2 (capture)**: Captures authorized funds via `PaymentPort.capture(payment_id, amount)` with key `order:{id}:capture` (`CAPTURED`).
- **S3 (hold)**: Atomic transaction writes `CAPTURE`, `HOLD`, and `FEE_RETAIN` rows in `payment.ledger` (`IN_ESCROW`).
- **S4 (settled)**: Emits `SettlementStep v1 (HELD)` to Kafka; Auction Orchestrator marks auction `SETTLED`.

### Failure & Compensation Matrix
- **S1 fails / winner abandons Checkout**: After 48-hour payment window expires, compensation cancels order and voids invoice (`CANCELLED`).
- **S2 transient failure**: Order moves to `AWAITING_CAPTURE_RETRY` with exponential backoff (1s, 2s, 4s... capped at 5m). Same idempotency key ensures no double-charge.
- **S3 definitive failure**: Compensation S2 executes: capture is reversed at provider (`order:{id}:reverse-capture`), compensation entries zero the ledger, and order moves to `CANCELLED`.

## Consequences

- **Idempotency**: Every step can be retried safely any number of times.
- **Operational visibility**: `saga_steps` tracks step status (`STARTED`, `SUCCEEDED`, `FAILED`, `COMPENSATED`).
- **Zero custody leaks**: Invariant tested in reconciliation suite with zero failures across 1,000 runs.

## Evidence

- Verified by `tests/e2e/test_lifecycle.py` and `tests/e2e/test_reconciliation.py`.
- Unit tests in `services/payment-escrow/tests/test_saga.py` validating S1-S4 and O4a compensation.
