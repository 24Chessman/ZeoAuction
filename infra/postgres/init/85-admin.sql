-- Schema: admin — Admin & Moderation (owner: Jay)
-- SDD 8.8, 9.1; FR-ADMIN-1..4.

-- Append-only record of every administrative action (FR-ADMIN-3). No UPDATE or DELETE grant,
-- and a trigger stops even the table owner.
CREATE TABLE admin.audit_log (
  id           bigserial PRIMARY KEY,
  actor_id     uuid NOT NULL,
  actor_role   text NOT NULL,
  service      text NOT NULL,          -- which service performed the action
  action       text NOT NULL,          -- e.g. KYC_APPROVE, USER_SUSPEND, DISPUTE_RESOLVE, KYC_DOC_VIEW
  target_type  text NOT NULL,
  target_id    uuid NOT NULL,
  before_state jsonb,
  after_state  jsonb,
  reason_code  text,
  note         text,
  request_id   uuid,
  at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_target_idx ON admin.audit_log (target_type, target_id);
CREATE INDEX audit_log_actor_idx ON admin.audit_log (actor_id);

CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON admin.audit_log
  FOR EACH ROW EXECUTE FUNCTION public.forbid_update_delete();

CREATE TABLE admin.listing_reviews (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  auction_id   uuid NOT NULL,
  source       text NOT NULL CHECK (source IN ('NEW_LISTING', 'USER_REPORT')),
  reported_by  uuid,
  reason       text,
  state        text NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING', 'APPROVED', 'REMOVED')),
  reviewed_by  uuid,
  decided_at   timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX listing_reviews_pending_idx ON admin.listing_reviews (created_at) WHERE state = 'PENDING';

CREATE TABLE admin.user_suspensions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL,
  reason_code   text NOT NULL,
  note          text,
  suspended_by  uuid NOT NULL,
  suspended_at  timestamptz NOT NULL DEFAULT now(),
  lifted_by     uuid,
  lifted_at     timestamptz
);

CREATE UNIQUE INDEX user_suspensions_one_active ON admin.user_suspensions (user_id) WHERE lifted_at IS NULL;

CREATE TABLE admin.broadcasts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title       text NOT NULL,
  body        text NOT NULL,
  created_by  uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT ON admin.audit_log TO admin_svc;
GRANT USAGE ON SEQUENCE admin.audit_log_id_seq TO admin_svc;
GRANT SELECT, INSERT, UPDATE ON admin.listing_reviews, admin.user_suspensions TO admin_svc;
GRANT SELECT, INSERT ON admin.broadcasts TO admin_svc;

-- Documented exception: services that perform admin actions append to the audit log
-- (INSERT only; they cannot read or change it).
GRANT USAGE ON SCHEMA admin TO kyc_svc, dispute_svc, payment_svc;
GRANT INSERT ON admin.audit_log TO kyc_svc, dispute_svc, payment_svc;
GRANT USAGE ON SEQUENCE admin.audit_log_id_seq TO kyc_svc, dispute_svc, payment_svc;
