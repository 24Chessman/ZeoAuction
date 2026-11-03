-- Schema: auth additions for user preferences and email OTPs (owner: Ayush)
-- Supports favorite auction categories for recommendation system and Gmail OTP authentication.

ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS favorite_categories text[] NOT NULL DEFAULT '{}'::text[];
ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS onboarded boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS auth.email_otps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext NOT NULL,
  otp_code text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz
);

CREATE INDEX IF NOT EXISTS email_otps_email_idx ON auth.email_otps (email, expires_at);
GRANT SELECT, INSERT, UPDATE, DELETE ON auth.email_otps TO auth_svc;
