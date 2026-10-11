# ZeoAuction

A distributed real-time auction platform: microservices / SOA, built by an M.Sc. IT (Semester 3) group project team of 8.

Sellers must pass KYC before they can list. Bids are sequenced deterministically under contention. Watchers see prices live
over WebSocket. Settlement charges a flat convenience fee and holds the funds in a **simulated** escrow for a buyer-protection
window, and a streaming detector flags shill bidding before the auction closes.

> **The escrow flow is a functional simulation.** Payment runs in test mode only, and no real money is ever handled.

## Where things are

| Path | What |
|---|---|
| `project_docs/` | Proposal, System Design Document (SDD), Jira timeline |
| `planing/` | The 8 implementation plans (two-week windows) |
| `commits/` | Who commits what, per plan |
| `services/` | 13 deployable services (10 APIs, 2 workers, 1 cron) |
| `libs/zeo-common/` | The service template every service is created from |
| `contracts/` | Frozen API and event contracts that services code against |
| `infra/` | PostgreSQL schemas, Kafka and S3 storage setup, Render Kafka image |
| `config/settlement-policy.yaml` | Fee, protection window, anti-snipe numbers |
| `docs/` | Architecture, state machines, ADRs, conventions |

## Run it locally

Prerequisites: Docker Desktop (about 6 GB of RAM for the full stack), plus Python 3.11+ for the tests.

```bash
docker compose up -d --build     # or: make up
docker compose ps                # every service should be "healthy"
make seed                        # development users and auctions
make verify-db                   # proves the schema guarantees (append-only ledger, ownership...)
```

| URL | What |
|---|---|
| http://localhost:8001 … 8012 `/healthz` | Services (see `docs/architecture.md` for the port map) |
| http://localhost:8004/api/v1/docs | API docs of a service (here: bid) |
| `localhost:8333` | S3 API (SeaweedFS; key `zeo-dev-access` / `zeo-dev-secret`) |
| `localhost:5432` | PostgreSQL (`postgres` / `postgres`, database `zeoauction`) |
| `localhost:29092` | Kafka from the host |

Schema changes only apply to a fresh database: `make reset && make up`.

**Windows notes:**
- `make` isn't installed by default, so run the command listed under each target in the `Makefile`.
- In Git Bash, prefix `docker compose exec` commands that pass container paths with `MSYS_NO_PATHCONV=1`.
  Otherwise Git Bash rewrites `/opt/...` into a Windows path.
- If the first `docker compose up --build` crashes Docker Desktop (13 images building in parallel), build them
  one at a time: `for s in $(docker compose config --services); do docker compose build $s; done`.

## Tests

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install ./libs/zeo-common -r requirements-dev.txt
ruff check .
sh scripts/test-all.sh           # shared library, contracts, every service
```

CI (`.github/workflows/ci.yml`) runs the same checks on every pull request.

## Team

| Member | Owns |
|---|---|
| Naitik | Bid Processing, Integration Testing |
| Sumit | Auction Orchestration, Documentation, Milestones |
| Sagar | KYC & Seller Verification, Pricing Engine, Search |
| Harshal | Fraud Detection |
| Jaydip | Payment, Fees & Escrow |
| Gaurang | Frontend |
| Jay | Dispute Management, Admin & Moderation |
| Ayush | Auth, WebSocket Gateway, Infrastructure |

See `docs/engineering-conventions.md` before opening your first PR.
