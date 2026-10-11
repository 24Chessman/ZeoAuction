# ws-gateway

| | |
|---|---|
| **Component** | WebSocket Gateway |
| **Interface owner** | Ayush |
| **Kind** | WebSocket service with a Kafka consumer |
| **Owns schema** | `notify` (database role `notify_svc`); not used until notification history (Plan 6) |
| **Design** | SDD 7.8, 7.8.1, Table 7.2 |
| **Plan 3** | #92 handshake and limits, #93 fan-out and outbid alerts, #94 reconnect and backpressure |

## Protocol

Connect to `ws://localhost:8010/ws` (also `/api/v1/ws`) with `?access_token=<JWT>` or `Authorization: Bearer`. The socket
carries no commands; bids go over REST.

| Direction | Message | Notes |
|---|---|---|
| C → S | `{"type":"subscribe","auction_id","last_seq"}` | Joins the room. If the gateway's snapshot is newer than `last_seq`, it answers with that `price_update` (FR-WS-3) |
| C → S | `{"type":"unsubscribe","auction_id"}` | Leaves the room |
| C → S | `{"type":"ping"}` | Answered with `pong`. The SPA pings every 25 s |
| S → C | `price_update` `{auction_id, current_price, min_next_bid, server_seq}` | To the room. Clients drop any `server_seq` not above the last seen |
| S → C | `outbid` `{auction_id, your_bid_id, current_price, server_seq}` | **Only** to the displaced bidder, on all their connections, in any room. Raising your own lead is not an outbid |
| S → C | `auction_extended` `{auction_id, new_closes_at}` | From `auction.events` `extend` |
| S → C | `auction_closed` `{auction_id, winning_bid_id}` | From any transition to `CLOSED` |
| S → C | `error` `{code, message, auction_id?}` | A refused client message; the connection stays open |

**Close codes:** `4401` missing, invalid or expired token (also on a `subscribe` after expiry): the SPA refreshes and
reconnects at once. `4429` too many connections for the user (5) or messages (20/s). `4408` silence for 75 s.
`1013` the client could not keep up; it reconnects and resubscribes for a snapshot.

## How fan-out works

A Kafka consumer on `bid.events` and `auction.events` turns events into messages (`app/fanout.py`). It never runs on a
request thread and never writes to a socket: it puts messages into each connection's outbox
(`app/backpressure.py`), and one writer task per connection drains it. So a slow watcher fills only its own outbox.

- While a `price_update` for an auction is still waiting, a newer one replaces it (last write wins, lossless in effect).
- `outbid`, `auction_extended`, `auction_closed` and notifications are never coalesced or dropped. If 256 of them pile
  up undelivered, the connection is closed with `1013` and the client resyncs from the snapshot.
- The snapshot (latest price and leader per auction) is kept per instance, and in Redis as `ws:room:{auction_id}`
  (expires 1 h after the last bid) so a restarted gateway can answer a resubscribe.
- `ws_fanout_latency_seconds` measures acceptance → queued for every watcher (target p95 < 100 ms at 500 watchers;
  `tests/test_reconnect.py` checks the in-process part with 500 watchers).

**One consumer group per instance** (`WS_CONSUMER_GROUP`, defaults to `ws-gateway-<hostname>`): every instance must see
every event for its own sockets. It starts at the latest offset, since reconnecting clients get the snapshot.

## Configuration

| Variable | Default |
|---|---|
| `WS_CONSUMER_GROUP` | `ws-gateway-<hostname>` |
| `WS_CONSUME_EVENTS`, `WS_USE_REDIS` | `true` |
| `WS_MAX_CONNECTIONS_PER_USER` | `5` |
| `WS_MAX_SUBSCRIPTIONS` | `50` |
| `WS_MAX_MESSAGES_PER_SECOND` | `20` |
| `WS_IDLE_TIMEOUT_SECONDS` | `75` |
| `WS_OUTBOX_LIMIT` | `256` |

## Run

```bash
docker compose up -d ws-gateway          # as part of the stack
cd services/ws-gateway && pytest         # unit tests (after installing libs/zeo-common)
```
