-- Schema: auth — Auth & User Service (owner: Ayush)
-- SDD 4.2.1, 7.2, 9.1. JWT claims are minted from users.role, kyc_status, suspended.

CREATE TABLE auth.users (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email           citext NOT NULL UNIQUE,
  password_hash   text NOT NULL,
  display_name    text NOT NULL,
  role            text NOT NULL DEFAULT 'USER' CHECK (role IN ('USER', 'ADMIN')),
  -- Deliberately denormalised mirror of kyc.kyc_submissions (SDD 4.2.1). Written ONLY by the
  -- KYC service (column-level grant below); a change forces token refresh.
  kyc_status      text NOT NULL DEFAULT 'NOT_SUBMITTED' CHECK (kyc_status IN (
                    'NOT_SUBMITTED', 'SUBMITTED', 'UNDER_REVIEW', 'VERIFIED', 'REJECTED', 'SUSPENDED')),
  kyc_status_updated_at timestamptz,
  -- Written by Admin & Moderation through the auth service API, never directly.
  suspended       boolean NOT NULL DEFAULT false,
  -- Bumped whenever a claim-bearing column changes; tokens minted with an older value are refused.
  token_version   integer NOT NULL DEFAULT 1,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER users_touch BEFORE UPDATE ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- Rotating refresh tokens (FR-AUTH-2). A token is used once; reuse of a rotated token
-- revokes the whole family, which is how a replayed refresh token is detected (SDD 9.1).
CREATE TABLE auth.refresh_tokens (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  family_id    uuid NOT NULL,
  token_hash   text NOT NULL UNIQUE,
  issued_at    timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  rotated_at   timestamptz,
  revoked_at   timestamptz,
  replaced_by  uuid REFERENCES auth.refresh_tokens (id)
);

CREATE INDEX refresh_tokens_family_idx ON auth.refresh_tokens (family_id);
CREATE INDEX refresh_tokens_user_idx ON auth.refresh_tokens (user_id);

GRANT SELECT, INSERT, UPDATE ON auth.users, auth.refresh_tokens TO auth_svc;

-- Documented cross-schema exception: KYC writes only the mirror columns (SDD 4.2.1).
GRANT USAGE ON SCHEMA auth TO kyc_svc;
GRANT SELECT (id, kyc_status, token_version) ON auth.users TO kyc_svc;
GRANT UPDATE (kyc_status, kyc_status_updated_at, token_version) ON auth.users TO kyc_svc;
