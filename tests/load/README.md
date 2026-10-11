# Load and concurrency rigs

| | |
|---|---|
| **Owner** | Naitik (Integration Testing) |
| **Jira** | #22 concurrency harness (Plan 3); #23 aggregate rig and week-9 baseline (Plan 4); the 1000 bids/s acceptance run follows in Plan 7 |

## `concurrency_harness.py`: contended single-auction bidding (FR-TEST-3, AC-02)

Drives a fixed rate of bids (200/s by default) at **one** auction, in bursts of simultaneous requests so they race
for the same compare-and-set, and checks:

1. **Replay agrees with live.** The accepted-bid log is replayed 100 times in shuffled arrival order through the
   pure resolver (`services/bid/app/domain/conflict.py::replay`). Every replay must name the live leader.
2. **Identical winner across runs.** The schedule (bidders, amounts, timing) comes from `--seed`, so runs end with
   the same winning bidder and amount, however the requests interleave. The number of accepted bids can differ
   between runs, and that's expected: contention changes which near-simultaneous bids win the race.

It prints one JSON line per run (achieved rate, outcomes by code, acknowledgement latency p50/p95/p99, winner) and a
final `PASS`/`FAIL` line. Exit status is non-zero on `FAIL`.

```bash
# In-process: the real hot path over in-memory Redis. No infrastructure needed.
.venv/Scripts/python.exe tests/load/concurrency_harness.py --rate 200 --duration 10 --runs 3

# Against the Compose stack (bid service on :8004, seeded OPEN auction):
docker compose up -d --build
.venv/Scripts/python.exe tests/load/concurrency_harness.py --mode http --runs 1 \
    --base-url http://localhost:8004 --auction 00000000-0000-4000-8000-000000000201
```

| Option | Default | Meaning |
|---|---|---|
| `--rate` | 200 | Bids per second |
| `--duration` | 10 | Seconds of bidding per run |
| `--burst` | 10 | Bids sent at the same instant |
| `--runs` | 3 | Independent runs with the same seed |
| `--replays` | 100 | Shuffled replays per run |
| `--seed` | 22 | Schedule seed |
| `--mode http` |  | Real HTTP; also `--base-url`, `--auction`, `--jwt-secret`, `--settle-seconds` |

**HTTP mode notes.** A price only goes up, so each HTTP run needs a fresh OPEN auction: use `--runs 1` per auction.
Tokens are minted with the local development JWT secret. The replay reads `GET /auctions/{id}/bids` after
`--settle-seconds`, so the flusher must be running.

**Where the numbers count.** In-process numbers measure the hot path's logic, not the system. Every acceptance
number (AC-02, the Plan 4 tuning baseline) comes from the dedicated load-test host (docs/architecture.md, section 4),
in HTTP mode.

`services/bid/tests/test_concurrency_harness.py` runs a one-second in-process version on every CI build.

## `aggregate_rig.py`: many auctions at once (#23, week-9 baseline)

Spreads an aggregate rate over `--auctions` auctions (default 1000 bids/s over 50), each contended in bursts, and
reports:

- acknowledgement latency p50/p95/p99, plus the **schedule lag** and the **intended** latency (lag + response). A
  saturated generator delays its own sends, and response latency alone would hide that (coordinated omission);
- in-process only: p50/p95/p99 **per SDD Table 9.3 segment** (idempotency, validation, sequencing/CAS,
  enqueue/publish, other), timed around every adapter call of the real hot path;
- for each auction, that replaying its accepted log names its live leader;
- a latency-vs-load curve with `--sweep`.

```bash
# In-process (indicative): the curve and the per-segment split
.venv/Scripts/python.exe tests/load/aggregate_rig.py --sweep 250,500,750,1000 --auctions 50 --duration 10 --markdown

# HTTP, against the load-test host (infra/loadtest/README.md): the numbers that count
python tests/load/aggregate_rig.py --mode http --base-url http://<host>:8004 --auction-ids ids.txt     --sweep 250,500,750,1000,1250 --duration 30 --markdown
```

The week-9 results and the identified bottleneck are in `docs/perf/week-09-baseline.md`.
`services/bid/tests/test_aggregate_rig.py` runs a one-second in-process version on every CI build.
