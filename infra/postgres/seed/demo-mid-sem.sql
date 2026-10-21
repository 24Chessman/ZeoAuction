-- Demo fixtures on top of dev-seed.sql (Plan 5 demo, segment 4). Run after dev-seed.sql; idempotent.
-- Two "ring" accounts and a listing for scripts/demo-shill.py, which makes them bid each other up
-- from one shared device so the fraud detector raises a ShillAlert before the auction closes.
-- Accounts log in with the dev seed password like the rest (password_hash "!seed").

BEGIN;

INSERT INTO auth.users (id, email, password_hash, display_name, role, kyc_status) VALUES
  ('00000000-0000-4000-8000-000000000006', 'ring1@zeo.local', '!seed', 'Ring Account One', 'USER', 'NOT_SUBMITTED'),
  ('00000000-0000-4000-8000-000000000007', 'ring2@zeo.local', '!seed', 'Ring Account Two', 'USER', 'NOT_SUBMITTED')
ON CONFLICT (id) DO NOTHING;

-- Listed by the verified seller of dev-seed.sql; open for two hours from when the seed runs.
INSERT INTO auction.auctions (
  id, seller_id, title, description, category, starting_price, reserve_price, currency, state,
  opens_at, closes_at, original_closes_at, guard_interval_seconds, extension_seconds, max_extensions
) VALUES
  ('00000000-0000-4000-8000-000000000203', '00000000-0000-4000-8000-000000000002',
   'Brass ship''s compass', 'Synthetic demo listing used for the shill-bidding segment.', 'antiques',
   2000.00, NULL, 'INR', 'OPEN', now(), now() + interval '2 hours', now() + interval '2 hours', 120, 120, 10)
ON CONFLICT (id) DO NOTHING;

INSERT INTO search.auction_index (
  auction_id, seller_id, title, description, category, current_price, currency, state,
  opens_at, closes_at, created_at
)
SELECT id, seller_id, title, description, category, starting_price, currency, state,
       opens_at, closes_at, created_at
FROM auction.auctions
WHERE id = '00000000-0000-4000-8000-000000000203'
ON CONFLICT (auction_id) DO NOTHING;

COMMIT;
