# auction-orchestrator

| | |
|---|---|
| **Component** | Auction Orchestration |
| **Interface owner** | Sumit |
| **Kind** | HTTP API service, plus the lifecycle timer and a `bid.events` consumer in the same process |
| **Owns schema** | `auction` (database role `auction_svc`) |
| **Design** | SDD 6.1; `docs/state-machines.md` §1; CT-1 `contracts/openapi/internal/auction-state.v1.yaml`; CT-2 `contracts/openapi/internal/kyc-status.v1.yaml` |
| **Plan 3** | #24 lifecycle guards (Naitik), #32 anti-snipe + `auction.events` (Sumit), #41 listing gate (Sagar) |

## Responsibility

The single source of auction lifecycle truth. Every transition goes through `app/domain/lifecycle.py` (rows A1–A8).
A pair outside the table is `409 CONFLICT` with `details {state, event}`; a guard that does not hold returns the code
the table names. Either way nothing changes.

| Method and path | Who | Purpose |
|---|---|---|
| `POST /api/v1/auctions` | **Listing gate** | Create a `DRAFT`. The seller is the token's subject; a `seller_id` in the body is refused |
| `GET /api/v1/auctions/{id}` | Public | Read a listing |
| `POST /api/v1/auctions/{id}/publish` | **Listing gate**, the seller | A1: `DRAFT` → `SCHEDULED`; needs `opens_at` (not in the past) and `closes_at` |
| `POST /api/v1/auctions/{id}/cancel` | The seller or an admin | A8: `DRAFT`/`SCHEDULED` → `CANCELLED`, only before any bid |
| `POST /api/v1/auctions/{id}/events` | Admin | Operator override of `open`, `close`, `drained`, `settle`; the table still applies |
| `GET /api/v1/auctions/{id}/state` | Internal | **CT-1**. `bid_permitted` is true exactly in `OPEN` and `EXTENDED` |

**Listing gate (CT-2, AC-06).** `zeo_common.gateway.VerifiedSeller` refuses, in order: a missing or invalid token (401),
a token older than the account's last KYC change (401, `details.reason = TOKEN_STALE`: refresh and retry), a suspended
account (`403 ACCOUNT_SUSPENDED`), and any `kyc_status` but `VERIFIED` (`403 SELLER_NOT_VERIFIED`). If the
token-version store is unreachable the gate fails closed (503). `tests/test_listing_gate_api.py` calls the API directly
with valid unverified tokens and checks zero auctions are created.

**Lifecycle timer** (`app/timers.py`, every second): A2 `open` when `opens_at` is reached, A5 `close` when `closes_at` is
reached, and A6 `drained` a grace period (`DRAIN_GRACE_SECONDS`, 5 s) after closing, so bids accepted just before the
deadline reach `bid.events` first. A6 sets `winning_bid_id` to the accepted bid with the highest `server_seq`.
Several instances are safe: the version check lets exactly one win.

**Anti-snipe (A4)** (`app/domain/anti_snipe.py`, fed by `bid.events`, group `auction-orchestrator`): a bid accepted within
`guard_interval_seconds` of `closes_at` moves the auction to `EXTENDED` and adds `extension_seconds`, at most
`max_extensions` times (120 s / 120 s / 10, from `config/settlement-policy.yaml`). Past the cap the bid stands and the
auction simply is not extended. The consumer also records `last_bid_seq` and `leading_bid_id`
(`infra/postgres/init/31-auction-bid-tracking.sql`); a redelivered event never extends twice.

**Events.** Every transition is published as `AuctionStateChanged v1` on `auction.events`, keyed by `auction_id`, after
the commit. The v1 enum has no `drained`, so A6 is published as `close` with `from_state = CLOSING`; consumers key off
`to_state`. If the broker is down, the transition stands and `auction_events_publish_failures` counts it.

Each write uses optimistic locking on `version` and records the transition in the append-only
`auction_state_transitions` table in the same transaction.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AUCTION_REPOSITORY` | `postgres` | `memory` runs without a database (no timer, consumer or Kafka) |
| `AUCTION_PUBLISHER` | `kafka` | `memory` keeps events in process |
| `CONSUME_BID_EVENTS` | `true` | Anti-snipe and leader tracking |
| `CHECK_TOKEN_FRESHNESS` | `true` | Listing gate checks `tv:{user_id}` in Redis |
| `RUN_LIFECYCLE_TIMER` | `true` | A2/A5/A6 in this process |
| `DRAIN_GRACE_SECONDS` | `5` | Wait between A5 and A6 |

## Run

```bash
docker compose up -d auction-orchestrator          # as part of the stack
cd services/auction-orchestrator && pytest         # unit tests (after installing libs/zeo-common)
```
