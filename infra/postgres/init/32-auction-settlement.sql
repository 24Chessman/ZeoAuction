-- Schema: auction — settlement hand-off to Payment (owner: Sumit; #33)
--
-- A6 drained names the winning bid. To open the order (saga S1, CT-4) Orchestration also needs
-- the winner and the amount, so the bid.events consumer keeps them for the leader alongside
-- leading_bid_id (BidAccepted v1 carries bidder_id and amount). They are frozen once the
-- auction is CLOSED, because no bid is recorded after A6.
--
-- settlement_order_id is set when Payment has opened the order. A CLOSED auction with a winner
-- and no order yet is retried by the lifecycle timer (Orchestration -> Payment breaker,
-- SDD Table 2.2): settlement is deferred, never abandoned. HELD on payment.events then applies
-- A7 settle.

ALTER TABLE auction.auctions
  ADD COLUMN leading_bidder_id   uuid,
  ADD COLUMN leading_amount      numeric(12, 2) CHECK (leading_amount > 0),
  ADD COLUMN settlement_order_id uuid;

-- The timer's scan for auctions waiting to be invoiced; the predicate keeps it tiny.
CREATE INDEX auctions_pending_settlement_idx ON auction.auctions (updated_at)
  WHERE state = 'CLOSED' AND winning_bid_id IS NOT NULL AND settlement_order_id IS NULL;
