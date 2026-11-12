# ADR-0006: Escrow sweep as a platform cron job

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.6, ratified in Plan 7, #37) |
| **Date** | 2026-11-02 |
| **Owner** | Naitik / Ayush |
| **Deciders** | Naitik, Ayush, Jaydip |
| **Requirements** | FR-PAY-5, AC-12; SDD §2.6.6; services/escrow-sweep/README.md |

## Context

When a seller marks an order `SHIPPED`, a 7-day buyer protection window opens.
If the buyer confirms receipt, funds release immediately. If the buyer never confirms
and never disputes, the platform must release the funds to the seller within 5 minutes (300 seconds)
of window expiration (AC-12).

## Options considered

1. **In-process timers / sleep delays**: lost on deployment restarts; cannot survive container rescheduling.
2. **Distributed delay queue (e.g. RabbitMQ / Redis sorted sets)**: introduces another infrastructure component and requires timer drift management.
3. **Dedicated scheduled cron job (`escrow-sweep`)**: runs every minute (`* * * * *`), performs an indexed query on `payment.orders`, and calls the Payment service internal release endpoint idempotently.

## Decision

**Option 3: Standalone Escrow Sweep Cron Job.**
1. Render runs `python -m app.sweep` every 60 seconds as a platform Cron Job (in Compose, runs in a 60-second loop).
2. The sweep role (`sweep_svc`) reads expired orders with a lean query:
   ```sql
   SELECT id, protection_window_ends_at FROM payment.orders
   WHERE state = 'SHIPPED' AND protection_window_ends_at <= $1
   ORDER BY protection_window_ends_at ASC
   ```
3. For each expired order, the sweep invokes:
   `POST /api/v1/internal/orders/{id}/release?trigger=sweep_expiry`
   authenticated by `X-Internal-Token` and with header `Idempotency-Key: order:{id}:release`.
4. Overlapping runs or retries are safe because the Payment service executes releases idempotently.
5. The sweep exports Prometheus metric `escrow_sweep_lag_seconds` and triggers an operational alert if lag exceeds 300 s.

## Consequences

- **Reliability**: Process crashes do not drop pending releases; the next minute's pass releases them immediately.
- **SLA adherence**: 60-second sweep cycle ensures releases happen well within the 300-second AC-12 threshold.
- **Isolation**: Heavy analytical batch queries do not impact the public-facing Payment API event loop.

## Evidence

- Verified in `services/escrow-sweep/tests/test_sweep.py` (100% pass).
- Time-accelerated end-to-end test in `tests/e2e/test_lifecycle.py` confirms Path b releases and enforces window closure.
