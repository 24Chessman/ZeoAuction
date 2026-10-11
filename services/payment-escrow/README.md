# payment-escrow

| | |
|---|---|
| **Component** | Payment, Fees & Escrow |
| **Interface owner** | Jaydip |
| **Kind** | HTTP API service |
| **Owns schema** | `payment` (database role `payment_svc`) |
| **Design** | SDD 4.3, 5.2, 6.2, 6.5, 7.4; ADR-0009, ADR-0011 |
| **Plan 2** | #59 pulled forward: `app/payment_port/` (`PaymentPort` + deterministic `MockPaymentAdapter`) |
| **Plan 3** | `GET /api/v1/fees/quote` stub for the pre-bid fee disclosure (#70, AC-07) |
| **Next work** | #60-#62 (Plan 4) |

## Responsibility

PaymentPort with mock and provider adapters, flat-fee quote, orders and invoices, the append-only escrow ledger, settlement saga, release and refund execution.
Test mode only: the escrow is a functional simulation and no real money moves.

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /api/v1/fees/quote?bid_amount=1250.00` | Public | `{bid_amount, convenience_fee, total, currency, fee_version}` (SDD Listing 7.3). Until the fee engine lands in Plan 4, it answers from the fixed `fee_config` of `config/settlement-policy.yaml` (`app/fees.py`); the shape and values stay the same |

## Run

```bash
docker compose up -d payment-escrow          # as part of the stack
cd services/payment-escrow && pytest         # unit tests (after installing libs/zeo-common)
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
