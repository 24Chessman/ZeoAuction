-- Development fixtures (owner: Ayush). Run with `make seed` (idempotent).
-- Fixed UUIDs so tests, scripts and the demo can reference the same actors.
-- password_hash is a placeholder: login works once the auth service lands (Plan 2, #91)
-- and re-hashes the dev password "zeo-dev-password" for these accounts.

BEGIN;

INSERT INTO auth.users (id, email, password_hash, display_name, role, kyc_status) VALUES
  ('00000000-0000-4000-8000-000000000001', 'admin@zeo.local',      '!seed', 'Dev Admin',           'ADMIN', 'NOT_SUBMITTED'),
  ('00000000-0000-4000-8000-000000000002', 'seller@zeo.local',     '!seed', 'Verified Seller',     'USER',  'VERIFIED'),
  ('00000000-0000-4000-8000-000000000003', 'unverified@zeo.local', '!seed', 'Unverified Seller',   'USER',  'NOT_SUBMITTED'),
  ('00000000-0000-4000-8000-000000000004', 'buyer1@zeo.local',     '!seed', 'Buyer One',           'USER',  'NOT_SUBMITTED'),
  ('00000000-0000-4000-8000-000000000005', 'buyer2@zeo.local',     '!seed', 'Buyer Two',           'USER',  'NOT_SUBMITTED')
ON CONFLICT (id) DO NOTHING;

INSERT INTO kyc.kyc_submissions (id, user_id, state, decided_at, decided_by) VALUES
  ('00000000-0000-4000-8000-000000000102', '00000000-0000-4000-8000-000000000002', 'VERIFIED',
   now(), '00000000-0000-4000-8000-000000000001')
ON CONFLICT (id) DO NOTHING;

INSERT INTO auction.auctions (
  id, seller_id, title, description, category, starting_price, reserve_price, currency, state,
  opens_at, closes_at, original_closes_at, guard_interval_seconds, extension_seconds, max_extensions
) VALUES
  ('00000000-0000-4000-8000-000000000201', '00000000-0000-4000-8000-000000000002',
   'Vintage film camera', 'Working 35mm rangefinder, synthetic demo listing.', 'cameras',
   8000.00, 12000.00, 'INR', 'OPEN', now(), now() + interval '2 days', now() + interval '2 days', 120, 120, 10),
  ('00000000-0000-4000-8000-000000000202', '00000000-0000-4000-8000-000000000002',
   'Mechanical keyboard', 'Draft listing, not yet published.', 'electronics',
   3000.00, NULL, 'INR', 'DRAFT', NULL, NULL, NULL, 120, 120, 10)
ON CONFLICT (id) DO NOTHING;

INSERT INTO search.auction_index (
  auction_id, seller_id, title, description, category, current_price, currency, state,
  opens_at, closes_at, created_at
)
SELECT id, seller_id, title, description, category, starting_price, currency, state,
       opens_at, closes_at, created_at
FROM auction.auctions
WHERE state <> 'DRAFT'
ON CONFLICT (auction_id) DO NOTHING;

COMMIT;
