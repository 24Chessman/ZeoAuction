# contracts/ — what every service codes against

The files in this folder are the published contracts between services, and between the platform and its clients.
They were frozen at the end of Plan 1. Implementations change to match the contracts, never the other way round.

| Path | Contract | Interface owner |
|---|---|---|
| `openapi/common.v1.yaml` | Error envelope, `Money`, auth scheme, idempotency and paging parameters | Sumit |
| `openapi/bid-service.v1.yaml` | Bid Processing public API (#18) | Naitik |
| `openapi/internal/auction-state.v1.yaml` | **CT-1**: Bid → Auction Orchestration state lookup | Sumit (provider) |
| `openapi/internal/pricing.v1.yaml` | **CT-3**: Bid → Pricing minimum increment | Sagar (provider) |
| `openapi/internal/kyc-status.v1.yaml` | **CT-2**: KYC status vocabulary and the listing gate's refusals | Sagar (provider), Sumit (enforcer) |
| `errors/common-error-codes.yaml` | Platform-wide error codes | Ayush |
| `errors/bid-rejection-codes.yaml` | Bid rejection taxonomy (SDD Table 5.1), final v1.0.0 since Plan 3 (#21) | Naitik |
| `events/topics.yaml` | Kafka topics, keys, retention, producers and consumers | Sumit |
| `events/bid_accepted.v1.json` | `BidAccepted v1` on `bid.events` (#50) | Harshal + Sumit |
| `events/auction_state_changed.v1.json` | `AuctionStateChanged v1` on `auction.events` | Sumit |
| `events/settlement_step.v1.json` | `SettlementStep v1` on `payment.events` | Jaydip |
| `events/shill_alert.v1.json` | `ShillAlert v1` on `fraud.alerts` | Harshal |

CT-2, the KYC listing gate, was pinned in Plan 3. It makes no call: the gate reads the JWT's `kyc_status`, `suspended`
and `tv` claims, and refuses tokens older than the last KYC change (`TOKEN_STALE`).

**Plan 3 changes:** `bid.events` gained the consumer group `auction-orchestrator` (anti-snipe and the drained winner).
`AuctionStateChanged v1` has no `drained` event, so the CLOSING → CLOSED step is published as `close` with
`from_state = CLOSING`; adding `drained` to the enum is a decision for the interface owner.

## Rules

1. **Changing a contract requires a PR approved by its interface owner**, plus the usual second approval.
2. **Versioning** (SDD 7.1):
   - Adding an optional field or a new rejection code is a minor bump (`info.version` 1.x).
   - Removing a field, renaming it, or changing its meaning is breaking. That needs `/api/v2` or a new event `schema_version`, and the old version stays served during a deprecation window.
3. **Money** is always a two-decimal string (`"1250.00"`) and never a JSON number.
4. **Events** carry `schema_version`, and consumers must ignore versions they don't know rather than crash.
5. Each service's FastAPI routes must produce an OpenAPI document that is compatible with its contract here. From Plan 7, CI compares the two.

## Validation

`pytest tests/contracts` checks the following:
- Every spec is valid OpenAPI 3.1.
- Every event example conforms to its schema.
- Money fields reject floats.
- Every bid rejection code is documented at its HTTP status.
- `topics.yaml` matches `infra/kafka/create-topics.sh`.
- The settlement policy matches the `fee_config` seed.
