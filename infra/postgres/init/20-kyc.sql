-- Schema: kyc — KYC & Seller Verification (owner: Sagar)
-- SDD 4.2.1, 6.3. States and transitions: docs/state-machines.md (Seller verification).

CREATE TABLE kyc.kyc_submissions (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           uuid NOT NULL,          -- auth.users.id (no cross-schema FK by design)
  state             text NOT NULL DEFAULT 'SUBMITTED' CHECK (state IN (
                      'SUBMITTED', 'UNDER_REVIEW', 'VERIFIED', 'REJECTED', 'SUSPENDED')),
  rejection_reason  text,
  submitted_at      timestamptz NOT NULL DEFAULT now(),
  decided_at        timestamptz,
  decided_by        uuid,                   -- admin user id
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (state <> 'REJECTED' OR rejection_reason IS NOT NULL)
);

-- At most one live submission per user; a REJECTED one can be superseded.
CREATE UNIQUE INDEX kyc_submissions_one_live_per_user
  ON kyc.kyc_submissions (user_id) WHERE state <> 'REJECTED';

CREATE TRIGGER kyc_submissions_touch BEFORE UPDATE ON kyc.kyc_submissions
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- Stores an object key, NEVER a URL: the key is resolved to a short-TTL signed URL at access
-- time (NFR-SEC-2). purge_after records the retention decision (FR-DOC-4, retention ADR).
CREATE TABLE kyc.kyc_documents (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id  uuid NOT NULL REFERENCES kyc.kyc_submissions (id) ON DELETE CASCADE,
  doc_type       text NOT NULL CHECK (doc_type IN ('GOVERNMENT_ID', 'PROOF_OF_ADDRESS', 'SELFIE')),
  object_key     text NOT NULL UNIQUE CHECK (object_key !~ '^[a-z]+://'),
  mime_type      text NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'application/pdf')),
  size_bytes     integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
  sha256         text NOT NULL,
  uploaded_at    timestamptz NOT NULL DEFAULT now(),
  purge_after    timestamptz NOT NULL
);

CREATE INDEX kyc_documents_submission_idx ON kyc.kyc_documents (submission_id);

-- Audit of every verification transition with actor and timestamp (FR-KYC-3). Append-only.
CREATE TABLE kyc.kyc_state_transitions (
  id             bigserial PRIMARY KEY,
  submission_id  uuid NOT NULL REFERENCES kyc.kyc_submissions (id),
  from_state     text,
  to_state       text NOT NULL,
  actor_id       uuid,
  reason         text,
  at             timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER kyc_state_transitions_append_only BEFORE UPDATE OR DELETE ON kyc.kyc_state_transitions
  FOR EACH ROW EXECUTE FUNCTION public.forbid_update_delete();

GRANT SELECT, INSERT, UPDATE ON kyc.kyc_submissions TO kyc_svc;
GRANT SELECT, INSERT, DELETE ON kyc.kyc_documents TO kyc_svc;   -- DELETE for the purge job
GRANT SELECT, INSERT ON kyc.kyc_state_transitions TO kyc_svc;
GRANT USAGE ON SEQUENCE kyc.kyc_state_transitions_id_seq TO kyc_svc;
