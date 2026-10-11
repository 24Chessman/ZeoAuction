-- ZeoAuction — database roles and schemas (owner: Ayush)
--
-- One PostgreSQL instance, one schema and one login role per service (SDD section 4.1).
-- Tables are created by the superuser, so service roles hold only the privileges granted
-- in each schema file. No service can read or write another service's tables; the few
-- deliberate exceptions are granted explicitly and listed in docs/architecture.md.
--
-- Passwords below are LOCAL DEVELOPMENT ONLY. Hosted credentials come from Render
-- environment groups and are never committed.
--
-- Files in this directory run once, in name order, on an empty data volume.
-- Re-run them with: docker compose down -v && docker compose up -d

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email

CREATE ROLE auth_svc    LOGIN PASSWORD 'auth_dev_pw';
CREATE ROLE kyc_svc     LOGIN PASSWORD 'kyc_dev_pw';
CREATE ROLE auction_svc LOGIN PASSWORD 'auction_dev_pw';
CREATE ROLE bid_svc     LOGIN PASSWORD 'bid_dev_pw';
CREATE ROLE pricing_svc LOGIN PASSWORD 'pricing_dev_pw';
CREATE ROLE payment_svc LOGIN PASSWORD 'payment_dev_pw';
CREATE ROLE dispute_svc LOGIN PASSWORD 'dispute_dev_pw';
CREATE ROLE search_svc  LOGIN PASSWORD 'search_dev_pw';
CREATE ROLE admin_svc   LOGIN PASSWORD 'admin_dev_pw';
CREATE ROLE notify_svc  LOGIN PASSWORD 'notify_dev_pw';
CREATE ROLE fraud_svc   LOGIN PASSWORD 'fraud_dev_pw';
CREATE ROLE sweep_svc   LOGIN PASSWORD 'sweep_dev_pw';

-- Nobody gets the default public schema.
REVOKE ALL ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA auth;
CREATE SCHEMA kyc;
CREATE SCHEMA auction;
CREATE SCHEMA bid;
CREATE SCHEMA pricing;
CREATE SCHEMA payment;
CREATE SCHEMA dispute;
CREATE SCHEMA search;
CREATE SCHEMA admin;
CREATE SCHEMA notify;
CREATE SCHEMA fraud;

-- Each role can see its own schema and resolves unqualified names there.
GRANT USAGE ON SCHEMA auth    TO auth_svc;
GRANT USAGE ON SCHEMA kyc     TO kyc_svc;
GRANT USAGE ON SCHEMA auction TO auction_svc;
GRANT USAGE ON SCHEMA bid     TO bid_svc;
GRANT USAGE ON SCHEMA pricing TO pricing_svc;
GRANT USAGE ON SCHEMA payment TO payment_svc;
GRANT USAGE ON SCHEMA dispute TO dispute_svc;
GRANT USAGE ON SCHEMA search  TO search_svc;
GRANT USAGE ON SCHEMA admin   TO admin_svc;
GRANT USAGE ON SCHEMA notify  TO notify_svc;
GRANT USAGE ON SCHEMA fraud   TO fraud_svc;

ALTER ROLE auth_svc    SET search_path = auth;
ALTER ROLE kyc_svc     SET search_path = kyc;
ALTER ROLE auction_svc SET search_path = auction;
ALTER ROLE bid_svc     SET search_path = bid;
ALTER ROLE pricing_svc SET search_path = pricing;
ALTER ROLE payment_svc SET search_path = payment;
ALTER ROLE dispute_svc SET search_path = dispute;
ALTER ROLE search_svc  SET search_path = search;
ALTER ROLE admin_svc   SET search_path = admin;
ALTER ROLE notify_svc  SET search_path = notify;
ALTER ROLE fraud_svc   SET search_path = fraud;
ALTER ROLE sweep_svc   SET search_path = payment;

-- Shared trigger function for tables that must be append-only
-- (escrow_ledger, audit_log, *_state_transitions). Grants already withhold UPDATE and
-- DELETE from service roles; the trigger also stops the table owner.
CREATE FUNCTION public.forbid_update_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% on %.% is forbidden: table is append-only',
    TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
    USING ERRCODE = 'insufficient_privilege';
END;
$$;

-- Shared trigger function maintaining updated_at columns.
CREATE FUNCTION public.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

GRANT USAGE ON SCHEMA public TO
  auth_svc, kyc_svc, auction_svc, bid_svc, pricing_svc, payment_svc,
  dispute_svc, search_svc, admin_svc, notify_svc, fraud_svc, sweep_svc;
