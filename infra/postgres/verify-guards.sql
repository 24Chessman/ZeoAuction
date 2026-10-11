-- Proves the storage-layer guarantees in the Plan 1 schema (owner: Ayush, with Jaydip for
-- the ledger). Run with `make verify-db` against a running stack. Every check runs inside a
-- rolled-back transaction, so it leaves no data behind. Any failure aborts with an error.
-- Table names are schema-qualified: a role's search_path applies at login, not after SET ROLE.

\set ON_ERROR_STOP on

BEGIN;

-- 1. Service roles cannot cross schema boundaries.
SET LOCAL ROLE bid_svc;
DO $$
BEGIN
  PERFORM 1 FROM payment.orders LIMIT 1;
  RAISE EXCEPTION 'FAIL: bid_svc could read payment.orders';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'ok: bid_svc cannot read payment.orders';
END $$;
RESET ROLE;

-- 2. The escrow ledger is append-only, even for the service that owns it.
INSERT INTO payment.orders (id, auction_id, buyer_id, seller_id, winning_bid_id,
  winning_bid_amount, convenience_fee, captured_total, currency, fee_version)
VALUES ('10000000-0000-4000-8000-000000000001', gen_random_uuid(), gen_random_uuid(),
  gen_random_uuid(), gen_random_uuid(), 100.00, 25.00, 125.00, 'USD', '2026-08-v1');

SET LOCAL ROLE payment_svc;
INSERT INTO payment.escrow_ledger (order_id, entry_type, amount, currency, idempotency_key) VALUES
  ('10000000-0000-4000-8000-000000000001', 'CAPTURE', 125.00, 'USD', 'order:1:capture'),
  ('10000000-0000-4000-8000-000000000001', 'HOLD', 0, 'USD', 'order:1:hold'),
  ('10000000-0000-4000-8000-000000000001', 'FEE_RETAIN', -25.00, 'USD', 'order:1:fee'),
  ('10000000-0000-4000-8000-000000000001', 'RELEASE', -100.00, 'USD', 'order:1:release');

DO $$
BEGIN
  UPDATE payment.escrow_ledger SET amount = 0 WHERE idempotency_key = 'order:1:release';
  RAISE EXCEPTION 'FAIL: ledger row was updated';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'ok: ledger UPDATE refused';
END $$;

-- 3. A second terminal row (release after release, or refund after release) is refused.
DO $$
BEGIN
  INSERT INTO payment.escrow_ledger (order_id, entry_type, amount, currency, idempotency_key)
  VALUES ('10000000-0000-4000-8000-000000000001', 'REFUND', -100.00, 'USD', 'order:1:refund');
  RAISE EXCEPTION 'FAIL: order was both released and refunded';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'ok: second terminal row refused';
END $$;

-- 4. Replaying an idempotency key is refused.
DO $$
BEGIN
  INSERT INTO payment.escrow_ledger (order_id, entry_type, amount, currency, idempotency_key)
  VALUES ('10000000-0000-4000-8000-000000000001', 'CAPTURE', 125.00, 'USD', 'order:1:capture');
  RAISE EXCEPTION 'FAIL: duplicate idempotency key accepted';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'ok: duplicate idempotency key refused';
END $$;

-- 5. The ledger for a terminal order sums to zero.
DO $$
DECLARE total numeric;
BEGIN
  SELECT sum(amount) INTO total FROM payment.escrow_ledger
  WHERE order_id = '10000000-0000-4000-8000-000000000001';
  IF total <> 0 THEN
    RAISE EXCEPTION 'FAIL: ledger sums to %', total;
  END IF;
  RAISE NOTICE 'ok: ledger sums to zero';
END $$;
RESET ROLE;

-- 6. Two bids cannot share a server_seq within one auction.
SET LOCAL ROLE bid_svc;
INSERT INTO bid.bids (id, auction_id, bidder_id, amount, server_seq, idempotency_key, accepted_at)
VALUES (gen_random_uuid(), '20000000-0000-4000-8000-000000000001', gen_random_uuid(),
        110.00, 1, 'bid-key-1', now());
DO $$
BEGIN
  INSERT INTO bid.bids (id, auction_id, bidder_id, amount, server_seq, idempotency_key, accepted_at)
  VALUES (gen_random_uuid(), '20000000-0000-4000-8000-000000000001', gen_random_uuid(),
          110.00, 1, 'bid-key-2', now());
  RAISE EXCEPTION 'FAIL: duplicate server_seq accepted';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'ok: duplicate server_seq refused';
END $$;
RESET ROLE;

-- 7. KYC may write only the mirror columns on auth.users.
SET LOCAL ROLE kyc_svc;
UPDATE auth.users SET kyc_status = 'VERIFIED' WHERE id = '00000000-0000-4000-8000-000000000003';
DO $$
BEGIN
  UPDATE auth.users SET role = 'ADMIN' WHERE id = '00000000-0000-4000-8000-000000000003';
  RAISE EXCEPTION 'FAIL: kyc_svc changed a user role';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'ok: kyc_svc cannot change roles';
END $$;
RESET ROLE;

-- 8. The audit log is append-only.
SET LOCAL ROLE admin_svc;
INSERT INTO admin.audit_log (actor_id, actor_role, service, action, target_type, target_id)
VALUES (gen_random_uuid(), 'ADMIN', 'admin-moderation', 'TEST', 'user', gen_random_uuid());
DO $$
BEGIN
  DELETE FROM admin.audit_log;
  RAISE EXCEPTION 'FAIL: audit log rows deleted';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'ok: audit log DELETE refused';
END $$;
RESET ROLE;

ROLLBACK;
\echo 'All schema guard checks passed.'
