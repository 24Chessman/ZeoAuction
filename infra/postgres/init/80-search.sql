-- Schema: search — Search & Analytics (owner: Sagar; seller dashboard: Gaurang)
-- SDD 4.2.1, 7.7. Search owns a PROJECTION of auctions built from auction.events and
-- bid.events, so it never reads auction.auctions directly. The SDD's
-- "auctions.search_vector with a GIN index" lives on this projection.

CREATE TABLE search.auction_index (
  auction_id     uuid PRIMARY KEY,
  seller_id      uuid NOT NULL,
  title          text NOT NULL,
  description    text NOT NULL DEFAULT '',
  category       text NOT NULL,
  current_price  numeric(12, 2) NOT NULL,
  currency       char(3) NOT NULL,
  state          text NOT NULL,
  opens_at       timestamptz,
  closes_at      timestamptz,
  created_at     timestamptz NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  search_vector  tsvector GENERATED ALWAYS AS (
                   setweight(to_tsvector('english', coalesce(title, '')), 'A')
                || setweight(to_tsvector('english', coalesce(category, '')), 'B')
                || setweight(to_tsvector('english', coalesce(description, '')), 'C')
                 ) STORED
);

CREATE INDEX auction_index_search_idx ON search.auction_index USING GIN (search_vector);
CREATE INDEX auction_index_filter_idx ON search.auction_index (state, closes_at);
CREATE INDEX auction_index_price_idx ON search.auction_index (current_price);
CREATE INDEX auction_index_seller_idx ON search.auction_index (seller_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON search.auction_index TO search_svc;
