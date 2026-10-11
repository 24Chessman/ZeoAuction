# payment-escrow

| | |
|---|---|
| **Component** | Payment, Fees & Escrow |
| **Interface owner** | Jaydip |
| **Kind** | HTTP API service, plus the settlement worker in the same process |
| **Owns schema** | `payment` (database role `payment_svc`) |
| **Design** | SDD 4.3, 5.2, 6.2, 6.5, 7.4; ADR-0009 (Razorpay), ADR-0011 (₹99 fee); `docs/state-machines.md` §2 |
| **Contracts** | `contracts/openapi/payment.v1.yaml`, CT-4 `contracts/openapi/internal/settlement.v1.yaml`, `SettlementStep v1` on `payment.events`, `contracts/errors/payment-error-codes.yaml` |
| **Plan 2** | #59 pulled forward: `PaymentPort` + deterministic `MockPaymentAdapter` |
| **Plan 3** | `GET /fees/quote` stub (#70, AC-07) |
| **Plan 4** | #61 fee engine, #62 escrow ledger, #60 Razorpay adapter, #34 invoice, #33 settlement S1–S3 + capture breaker |

## Responsibility

**Test mode only: the escrow is a functional simulation and no real money moves.** The Razorpay adapter refuses any
key that isn't `rzp_test_...`, and every order view carries `test_mode: true` and a notice.

Settlement forward path (the winner pays in Razorpay Checkout, ADR-0009):

```
auction CLOSED ──CT-4──▶ INVOICED ──Checkout──▶ AUTHORIZED ──capture──▶ CAPTURED ──hold──▶ IN_ESCROW ──HELD──▶ auction SETTLED
   (orchestrator)        order+invoice          signed handler            CAPTURE row         HOLD + FEE_RETAIN     (payment.events)
                         bid + ₹99 fee          or payment.authorized
```

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /api/v1/fees/quote?bid_amount=1250.00` | Public | `{bid_amount, convenience_fee, total, currency, fee_version}` from the active `fee_config` row. The same numbers the winner is invoiced |
| `POST /api/v1/internal/orders` | `X-Internal-Token` | **CT-4 / S1**: order + invoice for the winning bid. Idempotent per auction (201, then 200) |
| `GET /api/v1/orders/{id}`, `GET /api/v1/auctions/{id}/order` | Buyer, seller, admin | The order and its invoice |
| `POST /api/v1/orders/{id}/checkout` | The winner | Opens (once) the Razorpay order and returns what Checkout needs: `key_id`, `provider_order_id`, `amount_minor` (paise). With the mock adapter it also returns `simulated_payment` |
| `POST /api/v1/orders/{id}/payment` | The winner, `Idempotency-Key` | Checkout's `razorpay_order_id`, `razorpay_payment_id`, `razorpay_signature`. Verified, then captured into escrow |
| `POST /api/v1/webhooks/razorpay` (`/mock` locally) | Provider signature | `payment.authorized` does the same as the call above; deduplicated on `X-Razorpay-Event-Id` |
| `GET /api/v1/orders/{id}/ledger` | Admin | The append-only escrow ledger rows |

**Failures.** A capture that times out, or one attempted while the capture breaker is open (3 failures in 30 s), parks the
order in `AWAITING_CAPTURE_RETRY`. The settlement worker (`app/worker.py`, every 5 s) retries it with backoff and the same
key `order:{id}:capture`. The worker also resumes a capture that a crash interrupted (stuck in `AUTHORIZED` for more than
2 minutes), and cancels orders whose winner didn't pay within 48 h (O4). A declined capture compensates S1 the same way.
The ledger is untouched, the invoice is voided, and `COMPENSATED` is published.

**Mock adapter conventions** (offline demos): a total ending in `.13` is declined, and one ending in `.99` fails once and
then succeeds. With the ₹99 fee, a winning bid of `1250.13` gives a declined total of `1349.13`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PAYMENT_ADAPTER` | `mock` | `mock` or `razorpay` |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | – | Razorpay **test** API keys (Dashboard → Test Mode → API Keys) |
| `RAZORPAY_WEBHOOK_SECRET` | – | Secret of the webhook pointed at `/api/v1/webhooks/razorpay` (event `payment.authorized`) |
| `RAZORPAY_LINKED_ACCOUNT` | – | Route linked account (`acc_...`) that receives seller payouts in test mode |
| `INTERNAL_SERVICE_TOKEN` | dev value | Must equal the orchestrator's; protects CT-4 |
| `PAYMENT_WINDOW_HOURS` | `48` | How long the winner has to pay |
| `RUN_SETTLEMENT_WORKER`, `SETTLEMENT_WORKER_INTERVAL_SECONDS` | `true`, `5` | The worker |
| `PAYMENT_REPOSITORY`, `PAYMENT_PUBLISHER` | `postgres`, `kafka` | `memory` for local runs without infrastructure |

## Trying Razorpay test mode

1. Put the test keys in the repository's `.env` (git-ignored) with `PAYMENT_ADAPTER=razorpay`, and `docker compose up -d payment-escrow`.
2. In the frontend (`VITE_USE_MOCKS=false`), win an auction and press **Pay now**. Checkout opens in test mode. Pay with
   one of Razorpay's test cards or test UPI ids (see Razorpay's test-mode docs).
3. Checkout's signed handler is enough locally. Webhooks need a public URL, for example a tunnel to port 8006.

## Run

```bash
docker compose up -d payment-escrow          # as part of the stack
cd services/payment-escrow && ../../.venv/Scripts/python.exe -m pytest -q
```

Built from the shared template in `libs/zeo-common`: health, readiness, metrics, request ids and the error envelope are already wired in.
