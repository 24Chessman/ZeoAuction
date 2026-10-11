# Load-test host

| | |
|---|---|
| **Owner** | Ayush (infrastructure), for Naitik's baseline (#23) and the Plan 7 tuning (#24–#26) |
| **Machine** | Dedicated 8 vCPU / 16 GB, Ubuntu 22.04/24.04. **Every performance number used for acceptance comes from here** (`docs/architecture.md` §4) |
| **Generator** | A second machine on the same network runs `tests/load/aggregate_rig.py --mode http`, so the rig never steals CPU from the services |

## Set up

```bash
git clone <repo> && cd ZeoAuction
sh infra/loadtest/provision.sh              # Docker, sysctl/ulimit tuning, stack up, seed, 50 auction ids
# log out and back in once so the docker group applies, if Docker was just installed
```

The script:

1. installs Docker Engine and the compose plugin (skip with `--no-install`);
2. raises connection limits (`somaxconn`, local port range, `tw_reuse`, `nofile`) and sets the performance CPU governor;
3. writes `infra/loadtest/host-info.txt` (CPU, memory, kernel, commit) for the report;
4. builds the services **one at a time** (a parallel build can run out of memory) and starts the stack;
5. loads the development seed, then **50 fresh OPEN auctions** starting at ₹100.00 (`seed-auctions.sql`), and writes their ids to
   `infra/loadtest/ids.txt`.

`host-info.txt` and `ids.txt` are generated per host and git-ignored.

## Run a sweep

On the generator machine (Python with `requirements-dev.txt` and `libs/zeo-common` installed):

```bash
scp loadhost:ZeoAuction/infra/loadtest/ids.txt .
python tests/load/aggregate_rig.py --mode http --base-url http://<loadhost>:8004 \
    --auction-ids ids.txt --sweep 250,500,750,1000,1250 --duration 30 --markdown
```

A price only goes up, so **re-seed before each sweep**: `sh infra/loadtest/provision.sh --seed-only` creates 50 new
auctions and rewrites `ids.txt`.

While it runs, on the host:

```bash
docker stats --no-stream                                   # CPU per container: which one saturates first
docker compose exec redis redis-cli INFO commandstats      # Redis round trips per command
curl -s localhost:8004/metrics | grep bid_ack_latency      # server-side acknowledgement histogram
```

Record the results in `docs/perf/week-09-baseline.md` §6 (and later reports next to it).

## Rules

- Laptop numbers are **indicative only**; say so wherever they appear.
- Same commit, same seed (`--seed`), same duration across a sweep. Record the commit from `host-info.txt`.
- Report the **intended** latency (schedule lag + response) as well as the response latency, so a saturated
  generator can't hide queueing.
