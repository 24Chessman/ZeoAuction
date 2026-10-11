-- Schema: payment — Payment, Fees & Escrow (owner: Jaydip; invoice generation: Sumit)
-- SDD 4.3, 5.2, 6.2. Order states: docs/state-machines.md (Order settlement).
-- Payment owns all money. Dispute Management sends commands; it never writes these tables.

-- Flat convenience fee and protection window (ADR-0011). Fixed BEFORE any settlement code
-- is written: disclosure, invoice and settlement all read the same fee_version.
CREATE TABLE payment.fee_config (
  fee_version             text PRIMARY KEY,
  convenience_fee         numeric(12, 2) NOT NULL CHECK (convenience_fee >= 0),
  currency                char(3) NOT NULL,
  protection_window_days  integer NOT NULL CHECK (protection_window_days > 0),
  effective_from          timestamptz NOT NULL DEFAULT now(),
  active                  boolean NOT NULL DEFAULT false
);

-- Exactly one active fee configuration at a time.
CREATE UNIQUE INDEX fee_config_single_active ON payment.fee_config (active) WHERE active;

-- Values from config/settlement-policy.yaml (ADR-0011, status: Proposed).
INSERT INTO payment.fee_config (fee_version, convenience_fee, currency, protection_window_days, active)
VALUES ('2026-08-v1', 25.00, 'USD', 7, true);

CREATE TABLE payment.orders (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Settle exactly once per auction (SDD Table 6.1, "settle" guard).
  auction_id                uuid NOT NULL UNIQUE,
  buyer_id                  uuid NOT NULL,
  seller_id                 uuid NOT NULL,
  winning_bid_id            uuid NOT NULL,
  winning_bid_amount        numeric(12, 2) NOT NULL CHECK (winning_bid_amount > 0),
  convenience_fee           numeric(12, 2) NOT NULL CHECK (convenience_fee >= 0),
  captured_total            numeric(12, 2) NOT NULL,
  currency                  char(3) NOT NULL,
  fee_version               text NOT NULL REFERENCES payment.fee_config (fee_version),
  state                     text NOT NULL DEFAULT 'INVOICED' CHECK (state IN (
                              'INVOICED', 'AWAITING_CAPTURE_RETRY', 'CAPTURED', 'IN_ESCROW',
                              'SHIPPED', 'DISPUTED', 'RELEASED', 'REFUNDED', 'CANCELLED')),
  shipped_at                timestamptz,
  protection_window_ends_at timestamptz,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  version                   integer NOT NULL DEFAULT 1,
  -- Invariant: captured_total = winning_bid_amount + convenience_fee (SDD 4.3.2).
  CONSTRAINT orders_total_invariant CHECK (captured_total = winning_bid_amount + convenience_fee),
  CONSTRAINT orders_window_after_ship CHECK (
    (shipped_at IS NULL AND protection_window_ends_at IS NULL)
    OR (shipped_at IS NOT NULL AND protection_window_ends_at > shipped_at))
);

-- The escrow sweep's per-minute scan; the partial predicate keeps it small (SDD Table 4.1).
CREATE INDEX orders_sweep_idx ON payment.orders (protection_window_ends_at) WHERE state = 'SHIPPED';
CREATE INDEX orders_buyer_idx ON payment.orders (buyer_id);
CREATE INDEX orders_seller_idx ON payment.orders (seller_id);

CREATE TRIGGER orders_touch BEFORE UPDATE ON payment.orders
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TABLE payment.invoices (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id        uuid NOT NULL UNIQUE REFERENCES payment.orders (id),
  invoice_number  text NOT NULL UNIQUE,
  bid_amount      numeric(12, 2) NOT NULL,
  convenience_fee numeric(12, 2) NOT NULL,
  total           numeric(12, 2) NOT NULL,
  currency        char(3) NOT NULL,
  fee_version     text NOT NULL REFERENCES payment.fee_config (fee_version),
  issued_at       timestamptz NOT NULL DEFAULT now(),
  voided_at       timestamptz,              -- saga compensation for step S1
  CHECK (total = bid_amount + convenience_fee)
);

-- ---------------------------------------------------------------------------------------
-- The escrow ledger: the single source of monetary truth. APPEND-ONLY (ADR-0004).
-- Amounts are signed movements of platform custody for one order:
--   CAPTURE       > 0  buyer funds captured into custody (= captured_total)
--   HOLD          = 0  marker: captured total is under escrow hold
--   FEE_RETAIN    < 0  flat fee moved out of custody to platform revenue
--   RELEASE       < 0  net payout to the seller (captured_total - fee)
--   REFUND        < 0  reversal to the buyer (amount depends on fault, SDD Table 6.3)
--   COMPENSATION <> 0  equal-and-opposite reversal of an earlier row (a failed saga step,
--                      or +fee reversing FEE_RETAIN on a seller/platform-fault refund)
-- For every terminal order the rows sum to exactly zero (checked 1000x in FR-TEST-6).
-- ---------------------------------------------------------------------------------------
CREATE TABLE payment.escrow_ledger (
  id               bigserial PRIMARY KEY,
  order_id         uuid NOT NULL REFERENCES payment.orders (id),
  entry_type       text NOT NULL CHECK (entry_type IN (
                     'CAPTURE', 'HOLD', 'FEE_RETAIN', 'RELEASE', 'REFUND', 'COMPENSATION')),
  amount           numeric(12, 2) NOT NULL,
  currency         char(3) NOT NULL,
  -- Derived from order and operation, e.g. order:{id}:release (SDD 5.2.3). A retried
  -- webhook, duplicated delivery or double-clicked button converges on one row.
  idempotency_key  text NOT NULL UNIQUE,
  saga_id          uuid,
  compensates_id   bigint REFERENCES payment.escrow_ledger (id),
  provider_ref     text,
  note             text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ledger_sign_convention CHECK (
       (entry_type = 'CAPTURE'      AND amount > 0)
    OR (entry_type = 'HOLD'         AND amount = 0)
    OR (entry_type = 'FEE_RETAIN'   AND amount < 0)
    OR (entry_type = 'RELEASE'      AND amount < 0)
    OR (entry_type = 'REFUND'       AND amount < 0)
    OR (entry_type = 'COMPENSATION' AND amount <> 0 AND compensates_id IS NOT NULL))
);

CREATE INDEX escrow_ledger_order_idx ON payment.escrow_ledger (order_id);

-- No order may ever be both released and refunded, or released twice. The database refuses
-- the second terminal row even if application logic is wrong (SDD 4.3.2).
CREATE UNIQUE INDEX escrow_ledger_single_terminal
  ON payment.escrow_ledger (order_id) WHERE entry_type IN ('RELEASE', 'REFUND');

CREATE TRIGGER escrow_ledger_append_only BEFORE UPDATE OR DELETE ON payment.escrow_ledger
  FOR EACH ROW EXECUTE FUNCTION public.forbid_update_delete();

-- Saga progress per step, so a restarted coordinator resumes rather than repeats (Plan 5, #63).
CREATE TABLE payment.saga_steps (
  saga_id          uuid NOT NULL,
  step             text NOT NULL CHECK (step IN ('S1', 'S2', 'S3', 'S4', 'R1', 'R2', 'R3', 'R4')),
  order_id         uuid NOT NULL REFERENCES payment.orders (id),
  status           text NOT NULL CHECK (status IN ('PENDING', 'DONE', 'FAILED', 'COMPENSATED')),
  idempotency_key  text NOT NULL UNIQUE,
  attempts         integer NOT NULL DEFAULT 0,
  last_error       text,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (saga_id, step)
);

-- Provider webhook de-duplication (FR-PAY-7).
CREATE TABLE payment.provider_events (
  provider      text NOT NULL,
  event_id      text NOT NULL,
  event_type    text NOT NULL,
  received_at   timestamptz NOT NULL DEFAULT now(),
  processed_at  timestamptz,
  PRIMARY KEY (provider, event_id)
);

GRANT SELECT ON payment.fee_config TO payment_svc;
GRANT SELECT, INSERT, UPDATE ON payment.orders, payment.invoices, payment.saga_steps,
  payment.provider_events TO payment_svc;
GRANT SELECT, INSERT ON payment.escrow_ledger TO payment_svc;
GRANT USAGE ON SEQUENCE payment.escrow_ledger_id_seq TO payment_svc;

-- Documented exception: the escrow sweep reads (never writes) the columns it scans, and
-- releases through the Payment API with an idempotency key (ADR-0006).
GRANT USAGE ON SCHEMA payment TO sweep_svc;
GRANT SELECT (id, state, protection_window_ends_at) ON payment.orders TO sweep_svc;
