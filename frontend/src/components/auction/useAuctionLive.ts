import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveClient } from "@/app/live";
import { auctionApi, bidApi, type Auction, type BidAccepted, type BidPage } from "@/lib/api";
import { minimumNextBid } from "@/lib/bidRules";
import { parseMoney, type Cents } from "@/lib/money";

export interface LivePrice {
  price: Cents | null; // null until the first accepted bid
  minNext: Cents;
  seq: number;
}

export interface AuctionLive {
  auction: Auction;
  bids: BidPage;
  live: LivePrice;
  /** The bid being placed right now, shown optimistically until the server answers. */
  pending: Cents | null;
  /** server_seq of the caller's own leading bid, or null when they are not leading. */
  leadingSeq: number | null;
  flash: number;
  begin: (amount: Cents) => void;
  acknowledge: (ack: BidAccepted) => void;
  fail: () => void;
  refresh: () => Promise<void>;
}

function fromHistory(auction: Auction, bids: BidPage): LivePrice {
  const top = bids.items[0];
  const price = top ? parseMoney(top.amount) : null;
  return { price, minNext: minimumNextBid(price, parseMoney(auction.starting_price)), seq: top?.server_seq ?? 0 };
}

/**
 * Live state for one auction: REST history first, then price frames from the gateway.
 * Ordering is by server_seq only (the LiveClient drops anything not newer); a bid's own 202
 * acknowledgement is applied through the same check, so the socket and the ack reconcile.
 */
export function useAuctionLive(initialAuction: Auction, initialBids: BidPage): AuctionLive {
  const client = useLiveClient();
  const [auction, setAuction] = useState(initialAuction);
  const [bids, setBids] = useState(initialBids);
  const [live, setLive] = useState<LivePrice>(() => fromHistory(initialAuction, initialBids));
  const [pending, setPending] = useState<Cents | null>(null);
  const [leadingSeq, setLeadingSeq] = useState<number | null>(null);
  const [flash, setFlash] = useState(0);
  const id = initialAuction.auction_id;
  const historyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reloadHistory = useCallback(() => {
    if (historyTimer.current) clearTimeout(historyTimer.current);
    historyTimer.current = setTimeout(() => {
      bidApi.list(id, 1, 20).then(setBids, () => undefined);
    }, 300);
  }, [id]);

  const refresh = useCallback(async () => {
    const [nextAuction, nextBids] = await Promise.all([auctionApi.get(id), bidApi.list(id, 1, 20)]);
    setAuction(nextAuction);
    setBids(nextBids);
    const fromRest = fromHistory(nextAuction, nextBids);
    if (client.observe(id, fromRest.seq)) setLive(fromRest);
  }, [client, id]);

  useEffect(() => {
    client.subscribe(id, live.seq);
    const off = client.onMessage((message) => {
      if (message.type === "price_update" && message.auction_id === id) {
        setLive({ price: parseMoney(message.current_price), minNext: parseMoney(message.min_next_bid), seq: message.server_seq });
        setLeadingSeq((mine) => (mine !== null && mine !== message.server_seq ? null : mine));
        setFlash((n) => n + 1);
        reloadHistory();
      } else if (message.type === "outbid" && message.auction_id === id) {
        setLeadingSeq(null);
      } else if (message.type === "auction_extended" && message.auction_id === id) {
        setAuction((a) => ({ ...a, state: "EXTENDED", closes_at: message.new_closes_at, extension_count: a.extension_count + 1 }));
      } else if (message.type === "auction_closed" && message.auction_id === id) {
        void refresh();
      }
    });
    return () => {
      off();
      client.unsubscribe(id);
      if (historyTimer.current) clearTimeout(historyTimer.current);
    };
    // Subscribe once per auction; live.seq at mount is the starting point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, id]);

  // When the countdown passes, ask the server what happened rather than guessing.
  useEffect(() => {
    if (!auction.closes_at || (auction.state !== "OPEN" && auction.state !== "EXTENDED")) return;
    const wait = Date.parse(auction.closes_at) - Date.now() + 1500;
    const timer = setTimeout(() => void refresh(), Math.max(1000, wait));
    return () => clearTimeout(timer);
  }, [auction.closes_at, auction.state, refresh]);

  const begin = useCallback((amount: Cents) => setPending(amount), []);
  const fail = useCallback(() => setPending(null), []);
  const acknowledge = useCallback(
    (ack: BidAccepted) => {
      setPending(null);
      setLeadingSeq(ack.server_seq);
      if (client.observe(id, ack.server_seq)) {
        setLive({ price: parseMoney(ack.current_price), minNext: parseMoney(ack.min_next_bid), seq: ack.server_seq });
        setFlash((n) => n + 1);
      }
      reloadHistory();
    },
    [client, id, reloadHistory],
  );

  return { auction, bids, live, pending, leadingSeq, flash, begin, acknowledge, fail, refresh };
}
