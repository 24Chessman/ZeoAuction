-- Schema: auth additions for email verification links and password reset tokens (owner: Ayush)

ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS email_verified boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS auth.email_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  token_type text NOT NULL CHECK (token_type IN ('VERIFY_EMAIL', 'RESET_PASSWORD')),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz
);

CREATE INDEX IF NOT EXISTS email_tokens_user_type_idx ON auth.email_tokens (user_id, token_type);
CREATE INDEX IF NOT EXISTS email_tokens_hash_idx ON auth.email_tokens (token_hash);
GRANT SELECT, INSERT, UPDATE, DELETE ON auth.email_tokens TO auth_svc;
