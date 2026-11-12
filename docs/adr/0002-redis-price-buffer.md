# ADR-0002: Redis compare-and-set for current price, batched persistence

| | |
|---|---|
| **Status** | **Accepted** (SDD §2.6.2, ratified in Plan 7, #27) |
| **Date** | 2026-11-02 |
| **Owner** | Sumit / Naitik |
| **Deciders** | Sumit, Naitik, Ayush |
| **Requirements** | FR-BID-3, AC-01, AC-03; SDD §2.6.2, §5.2.2 |

## Context

Auctions in closing minutes experience burst traffic (up to 200 bids/s on a single item, and 1,000 bids/s globally).
Writing every individual bid synchronously to Postgres table `bid.bids` causes write amplifications,
row lock waits, and I/O saturation. However, buyers require real-time current price queries (<10ms)
and durable audit trails of every accepted bid.

## Options considered

1. **Synchronous Postgres INSERT on every bid**: guarantees immediate disk durability, but fails the 500 ms p95 acknowledgement latency SLA under contended loads.
2. **Pure in-memory buffering without Kafka**: high performance, but risks total loss of accepted bids during an unexpected process crash.
3. **Redis atomic CAS + Kafka write-ahead log + asynchronous batched flusher**: Redis holds active state for sub-millisecond atomic updates; Kafka provides durability before client acknowledgement (`acks=all`); dedicated `bid-flusher` batches writes to Postgres.

## Decision

**Option 3: Redis atomic price buffer with asynchronous batched persistence.**
1. Redis stores `price:{auction_id}`, `leader:{auction_id}`, and `seq:{auction_id}`.
2. The bid service validates and updates state in Redis via an atomic Lua script (CAS).
3. The bid is appended to Kafka topic `bid.events` with `acks=all` before HTTP 200/201 is returned to the bidder.
4. The standalone `bid-flusher` consumer reads `bid.events` in micro-batches (up to 100 records or 500 ms) and inserts them into Postgres using `COPY` / multi-row `INSERT ON CONFLICT DO NOTHING`.

## Consequences

- **Latency**: P95 acknowledgement latency is kept well under 200 ms (SLA < 500 ms).
- **Durability**: If `bid-flusher` or Postgres restarts, Kafka offsets ensure zero data loss.
- **Circuit breaker**: If Redis experiences transient degradation, state can be recovered from Kafka offsets.

## Evidence

- Load testing achieved 1,000 bids/s sustained across 50 auctions with 0 dropped bids.
- `bid-flusher` tests verify idempotent batch insertion with zero duplication.
