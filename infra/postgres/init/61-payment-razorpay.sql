-- Schema: payment — Razorpay Checkout settlement (owner: Jaydip; #33, #34, #60, #61, #62)
-- ADR-0009 (Accepted in Plan 4): Razorpay test mode with manual capture, currency INR.
--
-- 1. The fee moves to fee_version 2026-10-v1 (99.00 INR) before any order exists. The old row
--    stays (orders and invoices reference fee versions) but is no longer active.
-- 2. The winner pays through Razorpay Checkout, so an order waits for the buyer between the
--    invoice and the capture (docs/state-machines.md, section 2):
--      INVOICED --authorize--> AUTHORIZED --capture--> CAPTURED --hold--> IN_ESCROW
--    with AUTHORIZED --captureFailed--> AWAITING_CAPTURE_RETRY --capture--> CAPTURED.

UPDATE payment.fee_config SET active = false WHERE fee_version = '2026-08-v1';

-- Values from config/settlement-policy.yaml (tests/contracts/test_settlement_policy.py).
INSERT INTO payment.fee_config (fee_version, convenience_fee, currency, protection_window_days, active)
VALUES ('2026-10-v1', 99.00, 'INR', 7, true);

ALTER TABLE payment.orders DROP CONSTRAINT orders_state_check;
ALTER TABLE payment.orders ADD CONSTRAINT orders_state_check CHECK (state IN (
  'INVOICED', 'AUTHORIZED', 'AWAITING_CAPTURE_RETRY', 'CAPTURED', 'IN_ESCROW',
  'SHIPPED', 'DISPUTED', 'RELEASED', 'REFUNDED', 'CANCELLED'));

ALTER TABLE payment.orders
  -- One settlement saga per order; carried on every SettlementStep event.
  ADD COLUMN saga_id             uuid NOT NULL DEFAULT gen_random_uuid(),
  -- PaymentPort adapter that holds the money ('razorpay' or 'mock').
  ADD COLUMN provider            text NOT NULL DEFAULT 'mock',
  -- Razorpay order the buyer pays in Checkout (order_...); created once, reused on retries.
  ADD COLUMN provider_order_id   text UNIQUE,
  -- The authorised payment (pay_...), captured with key order:{id}:capture.
  ADD COLUMN provider_payment_id text,
  ADD COLUMN capture_ref         text,
  -- The winner must authorise payment by then (settlement-policy checkout.payment_window_hours).
  ADD COLUMN payment_due_at      timestamptz,
  ADD COLUMN authorized_at       timestamptz,
  ADD COLUMN capture_attempts    integer NOT NULL DEFAULT 0 CHECK (capture_attempts >= 0),
  ADD COLUMN next_capture_at     timestamptz,
  ADD CONSTRAINT orders_authorized_has_payment CHECK (
    state NOT IN ('AUTHORIZED', 'AWAITING_CAPTURE_RETRY', 'CAPTURED', 'IN_ESCROW')
    OR provider_payment_id IS NOT NULL);

-- The capture retrier's scan (Orchestration -> Payment breaker, SDD Table 2.2).
CREATE INDEX orders_capture_retry_idx ON payment.orders (next_capture_at)
  WHERE state = 'AWAITING_CAPTURE_RETRY';

-- The worker's other scans: captures a crash interrupted, and winners who never paid (O4).
CREATE INDEX orders_authorized_idx ON payment.orders (authorized_at) WHERE state = 'AUTHORIZED';
CREATE INDEX orders_payment_due_idx ON payment.orders (payment_due_at) WHERE state = 'INVOICED';
