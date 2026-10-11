-- Load-test fixtures (owner: Ayush, support for #23). LOAD-TEST HOST ONLY, never the dev seed.
-- Inserts 50 NEW OPEN auctions starting at 100.00 INR (tests/load/aggregate_rig.py plans bids
-- from there), listed by the seeded seller, and prints their ids for --auction-ids.
--
-- Every run gets fresh auctions instead of resetting old ones: a price only goes up, the
-- leader lives in Redis (price:{id}), and auction_state_transitions is append-only.
--
--   docker compose exec -T postgres psql -U postgres -d zeoauction -At -v ON_ERROR_STOP=1 \
--       -f /tmp/seed-auctions.sql > ids.txt   (provision.sh copies the file in first)

INSERT INTO auction.auctions (
  id, seller_id, title, description, category, starting_price, reserve_price, currency, state,
  opens_at, closes_at, original_closes_at, guard_interval_seconds, extension_seconds, max_extensions
)
SELECT
  gen_random_uuid(),
  '00000000-0000-4000-8000-000000000002',
  'Load-test lot ' || n, 'Synthetic listing for the load baseline (#23).', 'loadtest',
  100.00, NULL, 'INR', 'OPEN',
  now(), now() + interval '1 day', now() + interval '1 day', 120, 120, 10
FROM generate_series(1, 50) AS n
RETURNING id;
