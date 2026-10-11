-- Schema: auction — Auction Orchestration (owner: Sumit)
-- SDD 6.1. The lifecycle transition table is docs/state-machines.md (Auction lifecycle);
-- the service is the single source of lifecycle truth and rejects illegal transitions.

CREATE TABLE auction.auctions (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id               uuid NOT NULL,     -- auth.users.id; must be VERIFIED to publish
  title                   text NOT NULL CHECK (length(title) BETWEEN 3 AND 200),
  description             text NOT NULL DEFAULT '',
  category                text NOT NULL,
  starting_price          numeric(12, 2) NOT NULL CHECK (starting_price >= 0),
  reserve_price           numeric(12, 2) CHECK (reserve_price >= 0),
  currency                char(3) NOT NULL,
  state                   text NOT NULL DEFAULT 'DRAFT' CHECK (state IN (
                            'DRAFT', 'SCHEDULED', 'OPEN', 'EXTENDED', 'CLOSING',
                            'CLOSED', 'SETTLED', 'CANCELLED')),
  opens_at                timestamptz,
  closes_at               timestamptz,
  original_closes_at      timestamptz,
  -- Anti-snipe (FR-AO-4): values copied from config/settlement-policy.yaml at publish time.
  guard_interval_seconds  integer NOT NULL CHECK (guard_interval_seconds > 0),
  extension_seconds       integer NOT NULL CHECK (extension_seconds > 0),
  extension_count         integer NOT NULL DEFAULT 0 CHECK (extension_count >= 0),
  max_extensions          integer NOT NULL CHECK (max_extensions >= 0),
  winning_bid_id          uuid,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  version                 integer NOT NULL DEFAULT 1,   -- optimistic locking on transitions
  CHECK (extension_count <= max_extensions),
  CHECK (opens_at IS NULL OR closes_at IS NULL OR closes_at > opens_at)
);

-- Closing scan and "ending soonest" sort (SDD Table 4.1).
CREATE INDEX auctions_state_closes_idx ON auction.auctions (state, closes_at);
CREATE INDEX auctions_seller_idx ON auction.auctions (seller_id);

CREATE TRIGGER auctions_touch BEFORE UPDATE ON auction.auctions
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- Listing images are object keys (Cloudinary or S3 storage, per ADR-0010), never URLs.
CREATE TABLE auction.auction_images (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  auction_id  uuid NOT NULL REFERENCES auction.auctions (id) ON DELETE CASCADE,
  object_key  text NOT NULL,
  position    smallint NOT NULL DEFAULT 0,
  UNIQUE (auction_id, position)
);

-- Every lifecycle transition with actor and timestamp. Append-only.
CREATE TABLE auction.auction_state_transitions (
  id          bigserial PRIMARY KEY,
  auction_id  uuid NOT NULL REFERENCES auction.auctions (id),
  event       text NOT NULL,
  from_state  text,
  to_state    text NOT NULL,
  actor_id    uuid,              -- null for system events (timer, settlement)
  at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX auction_state_transitions_auction_idx ON auction.auction_state_transitions (auction_id);

CREATE TRIGGER auction_state_transitions_append_only
  BEFORE UPDATE OR DELETE ON auction.auction_state_transitions
  FOR EACH ROW EXECUTE FUNCTION public.forbid_update_delete();

GRANT SELECT, INSERT, UPDATE ON auction.auctions TO auction_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON auction.auction_images TO auction_svc;
GRANT SELECT, INSERT ON auction.auction_state_transitions TO auction_svc;
GRANT USAGE ON SEQUENCE auction.auction_state_transitions_id_seq TO auction_svc;
