-- Schema: bid — Bid Processing (owner: Naitik; batched writes by the bid-flusher worker, Sumit)
-- SDD 4.2.1, 4.4, 5.1. Rows arrive AFTER the client is acknowledged, in batches; ordering was
-- already fixed by server_seq and the event was already on bid.events (the recovery source).

CREATE TABLE bid.bids (
  id                  uuid PRIMARY KEY,               -- allocated on the hot path, not here
  auction_id          uuid NOT NULL,
  bidder_id           uuid NOT NULL,
  amount              numeric(12, 2) NOT NULL CHECK (amount > 0),
  server_seq          bigint NOT NULL CHECK (server_seq > 0),
  idempotency_key     text NOT NULL,
  device_fingerprint  text,
  increment_stale     boolean NOT NULL DEFAULT false, -- pricing breaker fallback was used
  accepted_at         timestamptz NOT NULL,
  persisted_at        timestamptz NOT NULL DEFAULT now(),
  -- Deterministic ordering enforced at the storage layer too (FR-BID-3): two bids can never
  -- occupy the same position, so a replay cannot produce a different winner.
  CONSTRAINT bids_auction_seq_unique UNIQUE (auction_id, server_seq),
  -- A retried submission collides and returns the original result (FR-BID-6).
  CONSTRAINT bids_idempotency_key_unique UNIQUE (idempotency_key)
);

-- Fraud ring clustering across auctions (FR-FRAUD-6).
CREATE INDEX bids_device_fingerprint_idx ON bid.bids (device_fingerprint)
  WHERE device_fingerprint IS NOT NULL;
CREATE INDEX bids_bidder_idx ON bid.bids (bidder_id);

-- Bids are facts: insert and read only.
GRANT SELECT, INSERT ON bid.bids TO bid_svc;
