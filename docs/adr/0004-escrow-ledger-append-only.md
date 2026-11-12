# ADR-0004: Escrow ledger is append-only

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.4, ratified in Plan 7, #68) |
| **Date** | 2026-11-02 |
| **Owner** | Jaydip |
| **Deciders** | Jaydip, Sumit, Ayush |
| **Requirements** | FR-PAY-4, AC-08; SDD §2.6.4, §4.3.2 |

## Context

Financial accounting requires immutable evidence of every monetary custody transition.
Updating balance columns in-place (`UPDATE orders SET balance = ...`) destroys transaction history,
creates write skew under concurrent triggers (e.g. concurrent refund and dispute resolution),
and makes post-incident forensic reconciliation virtually impossible.

## Options considered

1. **Mutable balance column on `orders` table**: simple schema, but loses history, risks race conditions, and lacks audit guarantees.
2. **Periodic snapshot tables**: captures balance at intervals, but misses intermediary intraday transitions.
3. **Immutable append-only ledger table with DB-level mutation denial**: each money movement is recorded as an immutable row (`payment.ledger`) with signed amounts and an idempotency key. Postgres triggers forbid any `UPDATE` or `DELETE`.

## Decision

**Option 3: Immutable append-only ledger with database trigger enforcement.**
1. Schema `payment.ledger` records every custody movement with:
   - `order_id`: UUID
   - `entry_type`: `CAPTURE`, `HOLD`, `FEE_RETAIN`, `COMPENSATION`, `RELEASE`, `REFUND`
   - `amount`: signed `NUMERIC(12, 2)`
   - `currency`: `CHAR(3)`
   - `idempotency_key`: unique constraint `(order_id, idempotency_key)`
   - `created_at`: UTC timestamp
2. DB trigger `ledger_append_only` raises an exception on any attempt to `UPDATE` or `DELETE` rows.
3. Account sign convention:
   - Positive (+): Custody entering platform from buyer (`CAPTURE`, `COMPENSATION`).
   - Negative (-): Custody leaving platform or committed to specific accounts (`HOLD`, `FEE_RETAIN`, `RELEASE`, `REFUND`).
4. Invariant: Every completed settlement (in terminal states `RELEASED`, `REFUNDED`, `CANCELLED`) must sum to exactly **ZERO** (`0.00`).

## Consequences

- **Auditability**: Administrators and reconciliation jobs can verify the complete ledger history at any time.
- **Concurrency**: Concurrency conflicts are prevented by the unique idempotency key constraint per movement.
- **Mathematical proof**: Reconciliation is a pure sum function over the order's ledger entries.

## Evidence

- Database schema verified in `infra/postgres/init/60-payment.sql`.
- 1,000-settlement reconciliation test (`tests/e2e/test_reconciliation.py`) confirmed 100% invariant adherence with 0 exceptions.
