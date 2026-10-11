# Week-9 load baseline (#23)

| | |
|---|---|
| **Owner** | Naitik (Bid Processing, integration testing), with Ayush (load-test host) |
| **Date** | 2026-10-10 (Plan 4, weeks 8–9) |
| **Target** | 1000 bids/s aggregate across 50 auctions; p95 bid acknowledgement ≤ 500 ms (SDD 9.3, AC-02) |
| **Status** | **Indicative run only.** The official run on the dedicated 8 vCPU / 16 GB host in HTTP mode hasn't happened yet; its table below is empty on purpose |
| **Rig** | `tests/load/aggregate_rig.py` (new), `tests/load/concurrency_harness.py` (Plan 3) |

## 1. What was run

```bash
.venv/Scripts/python.exe tests/load/aggregate_rig.py --sweep 250,500,750,1000 --auctions 50 --duration 10 --markdown
```

**In-process mode.** This is the bid service's real hot path: idempotency guard, CT-1 state, the leader read, CT-3
(stub tier table), funds, Lua compare-and-set, sequencing, publish and the flusher enqueue. It runs on **one asyncio
event loop** against **fakeredis**, with the load generator in the same process. There is no HTTP, no real Redis, no
Kafka and no PostgreSQL. Machine: developer laptop, Intel Core (Raptor Lake, 16 logical CPUs), Windows 11, Python
3.14.2. Each auction receives bursts of 5 simultaneous bids that tie, undercut and outbid each other.

Every adapter call is timed and attributed to its SDD Table 9.3 segment. **Schedule lag** is how late a bid left
against its planned time. Without it, a saturated generator hides queueing (coordinated omission), so
"intended" = lag + latency is the number to compare with the budget.

## 2. Results (indicative)

| Target bids/s | Achieved | Bids | p50 ms | p95 ms | p99 ms | p95 lag ms | **p95 intended ms** | CAS retries | Accepted / below increment | Replay = live (50 auctions) |
|---|---|---|---|---|---|---|---|---|---|---|
| 250 | 249.9 | 2500 | 0.99 | 3.45 | 6.54 | 21.02 | **22.55** | 0 | 866 / 1634 | yes |
| 500 | 496.8 | 5000 | 1.05 | 2.96 | 5.15 | 37.29 | **38.85** | 0 | 1775 / 3225 | yes |
| 750 | 704.5 | 7500 | 1.22 | 2.64 | 4.59 | 550.31 | **551.65** | 0 | 4392 / 3108 | yes |
| 1000 | 723.0 | 10000 | 1.23 | 2.60 | 4.22 | 3598.75 | **3599.97** | 0 | 5887 / 4113 | yes |

p95 per budget segment (ms):

| Segment (SDD 9.3) | Budget | @250/s | @500/s | @750/s | @1000/s |
|---|---|---|---|---|---|
| gateway | 40 | n/a in-process | | | |
| idempotency | 10 | 1.16 | 1.08 | 0.84 | 0.83 |
| validation | 180 | 0.44 | 0.42 | 0.36 | 0.35 |
| sequencing / CAS | 20 | 1.12 | 1.06 | 0.99 | 0.99 |
| enqueue / publish | 60 | 0.33 | 0.32 | 0.31 | 0.31 |
| response | 40 | n/a in-process | | | |
| other (domain logic, JSON) | – | 0.28 | 0.25 | 0.23 | 0.22 |
| **headroom** | 150 | | | | |

An earlier sweep without the lag column (250 → 3000 bids/s) showed the same plateau: the achieved rate peaked at
**≈ 725 bids/s** and fell slightly beyond that (620 at 3000/s).

## 3. Reading the curve

- **Every segment is far inside its budget**: about 3 ms per bid end to end, against 500 ms. Segment cost doesn't
  grow with load. This rig can't see real network or broker latency, so the 180 ms validation budget (which covers
  two internal HTTP calls) is untested here.
- **The knee is at ≈ 700 bids/s per event loop.** Below it the intended p95 is 22–39 ms; at 750/s the queue builds
  (p95 0.55 s, over budget); at 1000/s it's 3.6 s. **The target is missed in this configuration.**
- **Correctness held at every rate.** Every one of the 50 auctions replayed its accepted log to the same leader
  (AC-04 under load), with no duplicate or lost acknowledgements.
- **CAS retries were 0.** On one event loop the compare-and-set never truly interleaves, so this run says nothing
  about contention. The Plan 3 single-auction harness and the HTTP run are where conflict resolution is stressed.

## 4. The bottleneck

Profile of the 1000 bids/s run (`python -m cProfile`, 4 s):

- **≈ 72 % of CPU is the Redis client and fakeredis's in-process server emulation**: `redis.asyncio` `execute_command`
  5.9 s cumulative of 8.25 s.
- **4.8 Redis commands per bid** on average: **6 round trips for an accepted bid** (idempotency claim, leader read,
  `INCR seq`, CAS script, flusher enqueue, idempotency complete) and **3 for a rejected one** (claim, leader,
  complete).

So the in-process ceiling is mostly the rig's fake Redis, not the service. Two things carry over to the real stack:

1. **CPU per bid in one worker.** Even without fakeredis, one Python event loop is single-core. Expect a single
   uvicorn worker to saturate somewhere in the high hundreds to low thousands of bids/s. **1000 bids/s needs at least
   two bid-service workers or replicas.** That's safe because conflict resolution lives in Redis (the CAS), not in
   process memory.
2. **Serial Redis round trips.** On the host each of the 6 is a network round trip, on the critical path, in sequence.
   At 0.2–0.5 ms each on a local network that's 1–3 ms, which is fine. On Render's managed Key Value it's more, and it
   dominates the idempotency (10 ms) and sequencing/CAS (20 ms) budgets.

## 5. Tuning decision for conflict resolution

**No change to `services/bid/app/domain/conflict.py` this sprint.** There's no evidence for one: CAS retries were 0,
and the segments that do cost time are Redis round trips, not resolution logic. Tuning against fakeredis would
optimise the rig. The tuning focus for Plan 7 (#24–#26), in order, depends on the host run confirming the round-trip
picture:

1. Run the bid service with **2–4 workers** (`uvicorn --workers` or Render instances) and re-measure the knee.
2. **Fold `INCR seq` into the CAS Lua script** (sequence allocated only on a winning compare-and-set). That's one
   round trip less per accepted bid and no burned sequence numbers. Replay is unaffected because accepted bids stay
   ordered by `server_seq`. It needs Naitik's review of the AC-04 argument in `conflict.py`.
3. **Pipeline** the idempotency `complete` with the flusher enqueue (both after the decision): one more round trip
   saved.
4. Only if HTTP-mode CAS retries are high under contention: add a bounded jittered back-off between rounds
   (`MAX_RESOLUTION_ATTEMPTS` is 5 today).

## 6. Official run (dedicated host) — to be filled

Provision the host with `infra/loadtest/provision.sh` (Ayush). Then, from a second machine on the same network:

```bash
.venv/Scripts/python.exe tests/load/aggregate_rig.py --mode http --base-url http://<host>:8004 \
    --auction-ids ids.txt --sweep 250,500,750,1000,1250 --duration 30 --markdown
```

| Target bids/s | Achieved | p50 ms | p95 ms | p99 ms | p95 intended ms | CAS retries | Bottleneck observed |
|---|---|---|---|---|---|---|---|
| 250 | | | | | | | |
| 500 | | | | | | | |
| 1000 | | | | | | | |

Also record `bid_ack_latency_seconds` from `/metrics`, host CPU per container (`docker stats`), and Redis
`INFO commandstats`.
