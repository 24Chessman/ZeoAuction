# bid

| | |
|---|---|
| **Component** | Bid Processing |
| **Interface owner** | Naitik (Redis buffer, idempotency and Kafka producer: Sumit) |
| **Kind** | HTTP API service |
| **Owns schema** | `bid` (database role `bid_svc`, read side only; the bid-flusher writes) |
| **Design** | SDD 5.1, 6.4, 7.3; ADR-0001, ADR-0002; `contracts/openapi/bid-service.v1.yaml` |
| **Plan 2** | #19 validation, #20 conflict resolution, #29 producer, #30 price buffer, #31 idempotency |
| **Plan 3** | #21 final rejection taxonomy v1.0.0 (`app/errors.py`, `tests/test_rejections.py`); #22 contended single-auction harness (`tests/load/concurrency_harness.py`, CI run in `tests/test_concurrency_harness.py`) |

## Responsibility

The bid hot path (SDD 5.1.1), in this order, for `POST /api/v1/auctions/{id}/bids`:

1. **Idempotency guard**: `SET idem:{key} NX EX 86400`. A retry returns the stored outcome (`200` and
   `Idempotent-Replay: true`, or the original rejection). The unique `bids.idempotency_key` column is the backstop
   once Redis has forgotten the key.
2. **Validation, before any state change** (FR-BID-2): it reads CT-1 state, the current leader (`price:{id}`), the
   CT-3 increment and the stub funds limit, then checks `ACCOUNT_SUSPENDED` → `SELF_BIDDING_FORBIDDEN` →
   `AUCTION_NOT_OPEN` → `BID_BELOW_INCREMENT` → `INSUFFICIENT_FUNDS`.
3. **`server_seq` and compare-and-set** (ADR-0001): `INCR seq:{id}`, then a Lua compare-and-set on `price:{id}`
   that expects the leader the bid was validated against. A loser is re-validated against the new price, and either
   accepted at a fresh, higher `server_seq` or rejected. `AUCTION_CLOSED` is raised if `closes_at` has passed by then.
4. **Publish** `BidAccepted v1` to `bid.events`, keyed by `auction_id`, and wait for the broker's acknowledgement.
   If the publish fails, the compare-and-set is rolled back (unless someone has already outbid it) and the client gets
   `503 SERVICE_UNAVAILABLE`. So **every acknowledged bid is on Kafka**.
5. **Queue** the event on `flush:pending` for the bid-flusher, then reply **202** with `server_seq`,
   `current_price` and `min_next_bid`.

Why replay always gives the same winner: a bid is accepted only if the leader it was checked against is still the
leader, and its `server_seq` is higher than that leader's. So the accepted bids, in `server_seq` order, are exactly
what `app.domain.conflict.replay` re-derives from the log. `tests/test_replay_determinism.py` fires up to 50 equal
bids at once and replays the log 100 times in shuffled order.

`server_seq` is unique and increasing per auction, but it isn't gap-free: a lost compare-and-set or a failed publish
leaves a number unused.

## Endpoints

| Method and path | Auth | Notes |
|---|---|---|
| `POST /api/v1/auctions/{id}/bids` | bearer + `Idempotency-Key` | `202`, `200` (replay), `402`, `403`, `404`, `409`, `422`, `503` |
| `GET /api/v1/auctions/{id}/bids` | public | Newest first, by `server_seq`. Bidders appear as a per-auction alias, never by id |
| `GET /api/v1/bids/{id}` | bearer | Your own bids only; anyone else's is `404` |

History is read from PostgreSQL, so a bid accepted moments ago appears once the flusher has written it (within
`FLUSH_BATCH_MAX_AGE_MS`).

## Dependencies and fallbacks

| Dependency | Plan 2 | Fallback (SDD Table 2.2) |
|---|---|---|
| CT-1 auction state (`AUCTION_SERVICE_URL`) | auction-orchestrator | Breaker opens at 5 failures in 10 s. Cached state under 2 s old, else `503 AUCTION_STATE_UNAVAILABLE` |
| CT-3 increment (`PRICING_MODE`) | `stub`: a fixed tier table in the contract shape | With `http`: the last increment in `inc:{id}`, and the bid is flagged `increment_stale` |
| Funds (`STUB_FUNDS_LIMIT`) | Stub limit, default 100000.00 | Replaced once Payment offers a funds/hold API |
| Kafka (`BID_PUBLISHER=kafka`) | `acks=all`, idempotent producer | None. No acknowledgement from Kafka means no 202 |

Metrics: `bid_ack_latency_seconds` (histogram, the baseline for Plan 4), `bids_accepted_total`,
`bids_rejected_total{code}`, `bid_idempotent_replays_total` and `bid_cas_retries_total`.

## Run

```bash
docker compose up -d bid                                 # as part of the stack
cd services/bid && pytest --cov=app                      # unit tests (after installing libs/zeo-common)

# Place a bid on the seeded open auction (login first: buyer1@zeo.local / zeo-dev-password)
TOKEN=$(curl -s localhost:8001/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"buyer1@zeo.local","password":"zeo-dev-password"}' | python -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
curl -i localhost:8004/api/v1/auctions/00000000-0000-4000-8000-000000000201/bids \
  -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: demo-bid-0001' \
  -H 'Content-Type: application/json' -d '{"amount":"100.00"}'
```

Built from the shared template in `libs/zeo-common`, so health, readiness (Redis, PostgreSQL, Kafka), metrics,
request ids, JWT verification and the error envelope are already wired in.
