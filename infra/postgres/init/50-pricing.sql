-- Schema: pricing — Pricing Engine (owner: Sagar)
-- SDD 2.4, 7.2. The hot increment lives in Redis (inc:{auction_id}); these tables are the
-- durable configuration and history behind it. Draft — tuned in Plan 4 (#42-#44).

-- Base increment ladder by price band, scaled by velocity at runtime.
CREATE TABLE pricing.increment_rules (
  id                   serial PRIMARY KEY,
  price_from           numeric(12, 2) NOT NULL CHECK (price_from >= 0),
  price_to             numeric(12, 2),                -- null = no upper bound
  base_increment       numeric(12, 2) NOT NULL CHECK (base_increment > 0),
  velocity_multiplier  numeric(6, 3) NOT NULL DEFAULT 1.0 CHECK (velocity_multiplier >= 1.0),
  CHECK (price_to IS NULL OR price_to > price_from)
);

-- Rolling bid-rate buckets per auction (FR-PRICE-1).
CREATE TABLE pricing.velocity_windows (
  auction_id    uuid NOT NULL,
  window_start  timestamptz NOT NULL,
  window_secs   integer NOT NULL CHECK (window_secs > 0),
  bid_count     integer NOT NULL CHECK (bid_count >= 0),
  PRIMARY KEY (auction_id, window_start)
);

CREATE TABLE pricing.hot_auction_flags (
  auction_id  uuid PRIMARY KEY,
  flagged_at  timestamptz NOT NULL DEFAULT now(),
  reason      text NOT NULL,
  cleared_at  timestamptz
);

-- Starting ladder; values are placeholders until Plan 4 tuning.
INSERT INTO pricing.increment_rules (price_from, price_to, base_increment) VALUES
  (0.00,     100.00,   1.00),
  (100.00,   1000.00,  5.00),
  (1000.00,  10000.00, 25.00),
  (10000.00, NULL,     100.00);

GRANT SELECT ON pricing.increment_rules TO pricing_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON pricing.velocity_windows, pricing.hot_auction_flags TO pricing_svc;
