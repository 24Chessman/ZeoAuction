# bid-flusher

| | |
|---|---|
| **Component** | Bid batch flusher (worker) |
| **Interface owner** | Sumit |
| **Kind** | Background worker. Its HTTP surface is health, readiness and metrics only |
| **Owns schema** | `bid` (shares the `bid_svc` role with the bid service) |
| **Design** | SDD 4.4; ADR-0002 |
| **Plan 2** | #30 batched persistence and Kafka replay recovery |

## Responsibility

**Batched persistence.** This worker drains `flush:pending` (accepted `BidAccepted v1` events queued by the bid
service) into `bid.bids`, in batches bounded by **size** (`FLUSH_BATCH_MAX_SIZE`, 500) and **age**
(`FLUSH_BATCH_MAX_AGE_MS`, 500 ms). Delivery is at least once: a batch is read, written in one transaction with
`ON CONFLICT DO NOTHING`, and only then trimmed from the list. So a crash between the two just rewrites the same rows,
which the constraints ignore. Records that can't be parsed go to `flush:dead` instead of blocking the queue.
On shutdown, the worker drains everything that's left.

**Crash recovery by Kafka replay.** Kafka is the recovery source, not Redis. On start (`REPLAY_ON_START`), or on
demand, `app/replay.py` reads the retained `bid.events` and:
- persists every bid above the last persisted `server_seq` of its auction;
- raises `seq:{id}` to the highest sequence seen, so no number is reused;
- restores `price:{id}` to the latest leader.

It never lowers live Redis state, and running it twice changes nothing.

```bash
docker compose exec bid-flusher python -m app.replay     # manual replay
```

`tests/test_flusher.py::test_crash_recovery_by_replay_restores_the_unflushed_batch` is the demonstration. Ten bids are
published, one batch of four is flushed, then Redis is wiped. The replay restores the other six rows, `seq:{id}` = 10,
and the leader.

Exactly one instance runs (a Render background worker), because it's the only process that trims the head of
`flush:pending`.

Metrics: `bid_flush_rows_total`, `bid_flush_batch_size`, `bid_flush_pending` (queue depth),
`bid_flush_dead_letters_total` and `bid_replay_rows_total`.

## Run

```bash
docker compose up -d bid-flusher          # as part of the stack
cd services/bid-flusher && pytest         # unit tests (after installing libs/zeo-common)
```
