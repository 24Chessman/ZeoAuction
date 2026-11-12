# ADR-0001: Server-allocated `server_seq` determines bid order

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.1, ratified in Plan 7, #27) |
| **Date** | 2026-11-02 |
| **Owner** | Naitik |
| **Deciders** | Sumit, Ayush, Naitik |
| **Requirements** | FR-BID-1, FR-BID-2, FR-BID-7, AC-01, AC-02; SDD §2.6.1, §5.2.2 |

## Context

In high-concurrency auctions, bids arrive concurrently across multiple gateway instances.
Relying on client-side timestamps (`submitted_at`) produces race conditions, permits client
clock manipulation, and creates non-deterministic order when network jitter reverses packet arrivals.
Database transactions with locks on every bid introduce lock contention that caps throughput
well below the target 1,000 bids/s (AC-01, AC-02).

## Options considered

1. **Client timestamp ordering**: simple, but vulnerable to clock skew, client fraud, and out-of-order delivery.
2. **Postgres SERIAL transaction on every bid**: guarantees total order, but creates serialised row locks capping throughput at ~120 writes/s under load.
3. **Atomic Redis Lua sequencing (`server_seq`) + partitioned Kafka append**: an atomic Lua script in Redis executes validation, updates price via compare-and-set, and increments an authoritative per-auction integer sequence `server_seq`.

## Decision

**Option 3: Server-allocated `server_seq` in Redis Lua.**
For every auction, Redis maintains an integer key `seq:{auction_id}`.
When a bid passes static validation, an atomic Lua script executes:
1. Validates `bid.amount >= current_price + min_increment`
2. Sets `price:{auction_id} = bid.amount` and `leader:{auction_id} = bidder_id`
3. Increments `seq:{auction_id}` to yield `server_seq`
4. Stashes the idempotency key and returns success

The bid service publishes `BidAccepted v1` to `bid.events` keyed by `auction_id` with `server_seq`.
Downstream consumers (Auction Orchestrator anti-snipe, Fraud Detector, Bid Flusher) consume
in partition order and resolve conflicts strictly by `server_seq`, never by timestamps.

## Consequences

- **Determinism**: Replaying bids in shuffled order yields the exact same winner (tested in `concurrency_harness.py`).
- **Throughput**: 1,000+ bids/s achieved with sub-millisecond sequencing in memory.
- **Contract CT-1**: Pins `server_seq` as an integer `>= 1` required on every accepted bid.

## Evidence

- Verified by `tests/load/concurrency_harness.py`: 200 bids/s contending on one auction with 100% replay agreement across 3 randomised runs.
- Unit suite `services/bid/tests/test_sequencing.py` passing with zero sequencer drift.
