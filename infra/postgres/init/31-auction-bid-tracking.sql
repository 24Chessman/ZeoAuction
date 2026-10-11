-- Schema: auction — bid tracking for anti-snipe and the drained step (owner: Sumit; #24, #32)
--
-- Auction Orchestration consumes bid.events (group auction-orchestrator) and keeps, per
-- auction, the highest server_seq it has applied and that bid's id. It needs them for:
--   * A4 extend: decided per accepted bid, and a redelivered event (server_seq not above
--     last_bid_seq) must never extend twice;
--   * A6 drained: winning_bid_id is the bid with the highest accepted server_seq;
--   * A8 cancel: "no accepted bids exist" is last_bid_seq = 0.
-- closing_since starts the drain grace period that A6 waits for after A5 close.
-- Ordering comes from server_seq, never from timestamps (docs/engineering-conventions.md).

ALTER TABLE auction.auctions
  ADD COLUMN last_bid_seq   bigint NOT NULL DEFAULT 0 CHECK (last_bid_seq >= 0),
  ADD COLUMN leading_bid_id uuid,
  ADD COLUMN closing_since  timestamptz;

-- The opening scan of the lifecycle timer (A2); the closing scan uses auctions_state_closes_idx.
CREATE INDEX auctions_state_opens_idx ON auction.auctions (state, opens_at);
