# pricing

| | |
|---|---|
| **Component** | Pricing Engine |
| **Interface owner** | Sagar |
| **Kind** | HTTP API service + `bid.events` consumer (group `pricing`) |
| **Owns schema** | `pricing` (database role `pricing_svc`) |
| **Design** | SDD 2.4, 7.2 (Pricing); contracts/openapi/internal/pricing.v1.yaml (CT-3) |
| **Plan 4** | #42 velocity, #43 dynamic increment + CT-3, #44 hot-auction flag |

## Responsibility

Bid-velocity tracking, dynamic minimum increment (contract CT-3), hot-auction flagging.

| Route (internal) | What |
|---|---|
| `GET /api/v1/pricing/{auctionId}/min-increment?current_price=` | `min_increment`, `min_next_bid`, `hot` (CT-3). Also refreshes `inc:{auction_id}` (60 s) |
| `GET /api/v1/pricing/{auctionId}/velocity` | `bids_per_minute` over the rolling window and `hot` (FR-PRICE-1) |

## How the numbers are made

- **Velocity (#42)** — `app/domain/velocity.py`. Accepted bids from `bid.events` go into 5 s buckets; the rate is the
  count in the last 60 s, per minute. A replayed `server_seq` is not counted twice. Dirty buckets are flushed to
  `pricing.velocity_windows` every 5 s and restored on start-up, so a restart doesn't zero a busy auction.
- **Increment (#43)** — `app/domain/increment.py`. The price band in `pricing.increment_rules`
  (`infra/postgres/init/51-pricing-dynamic.sql`) gives the base; velocity raises it linearly up to the band's
  `velocity_multiplier` (2×) at 60 bids/min; the result is rounded half-up to whole rupees.
  **The base is a floor**: it equals Bid Processing's fallback tier table, which the bid replay (AC-04) also uses, so
  a live-accepted bid always clears the replay's bar. Tests in both services pin the two tables to the SQL file.
- **Hot flag (#44)** — `app/domain/hot_auction.py`. Hot at ≥ 30 bids/min, cleared below 15 (hysteresis). Changes go to
  `pricing.hot_auction_flags` and the `pricing_hot_auctions` gauge; the flag is on both routes.

If Pricing is down, Bid Processing's CT-3 breaker (5 failures / 10 s) uses the cached `inc:{auction_id}`, never below
the tier floor, and flags the bid `increment_stale` (`services/bid/tests/test_ct3_breaker.py`).

Run **one replica**: velocity is in memory, so the single member of the `pricing` group must see every partition.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PRICING_REPOSITORY` | `postgres` | `memory` runs without PostgreSQL/Redis/Kafka (default ladder, no cache) |
| `CONSUME_BID_EVENTS` | `true` | Feed velocity from `bid.events` |
| `PRICING_WINDOW_SECONDS` / `PRICING_BUCKET_SECONDS` | `60` / `5` | Rolling window and bucket width |
| `PRICING_SATURATION_BPM` | `60` | Velocity at which the increment reaches the band multiplier |
| `HOT_ENTER_BPM` / `HOT_EXIT_BPM` | `30` / `15` | Hot-flag thresholds |
| `INCREMENT_CACHE_TTL_SECONDS` | `60` | `inc:{auction_id}` lifetime |
| `VELOCITY_FLUSH_SECONDS` | `5` | Bucket flush interval |

## Run

```bash
docker compose up -d pricing          # as part of the stack (bid uses PRICING_MODE=http)
cd services/pricing && ../../.venv/Scripts/python.exe -m pytest -q
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
