-- Schema: pricing — dynamic increment ladder (owner: Sagar, #43). Plan 4.
-- Replaces the placeholder ladder seeded by 50-pricing.sql (that file is left untouched).
--
-- base_increment is the FLOOR of the dynamic increment and must equal Bid Processing's
-- fallback tier table (services/bid/app/adapters/pricing_client.py::INCREMENT_TIERS): the bid
-- service's replay (AC-04) re-derives the winner with that table, so no live increment may be
-- smaller. Tests in both services parse the rows below and compare.
--
-- velocity_multiplier is the factor reached at the saturation velocity (PRICING_SATURATION_BPM,
-- default 60 bids/min); the increment grows linearly from 1x to it (app/domain/increment.py).

DELETE FROM pricing.increment_rules;

INSERT INTO pricing.increment_rules (price_from, price_to, base_increment, velocity_multiplier) VALUES
  (0.00,    100.00,  1.00,  2.000),
  (100.00,  500.00,  5.00,  2.000),
  (500.00,  1000.00, 10.00, 2.000),
  (1000.00, 5000.00, 25.00, 2.000),
  (5000.00, NULL,    50.00, 2.000);

-- Active flags are looked up on start-up to restore the hot set.
CREATE INDEX hot_auction_flags_active_idx ON pricing.hot_auction_flags (auction_id)
  WHERE cleared_at IS NULL;
