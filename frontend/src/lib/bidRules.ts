import type { AuctionState } from "./api/types";
import type { Cents } from "./money";

/**
 * The client mirrors the bid service's checks exactly (services/bid/app/domain/validation.py),
 * in the same order: suspended -> self-bidding -> auction open -> increment. The funds check
 * is the server's alone. Nothing here is a rule the server does not enforce.
 */

/** Same tiers as the bid service's CT-3 stub and the ws-gateway (until the Pricing Engine). */
const TIERS: ReadonlyArray<[Cents | null, Cents]> = [
  [10_000, 100],
  [50_000, 500],
  [100_000, 1_000],
  [500_000, 2_500],
  [null, 5_000],
];

export function tierIncrement(price: Cents): Cents {
  for (const [upper, increment] of TIERS) {
    if (upper === null || price < upper) return increment;
  }
  throw new Error("unreachable");
}

/** Starting price until someone bids, then the leader plus the increment. */
export function minimumNextBid(leader: Cents | null, starting: Cents): Cents {
  return leader === null ? starting : leader + tierIncrement(leader);
}

export const BIDDABLE: ReadonlySet<AuctionState> = new Set(["OPEN", "EXTENDED"]);

export interface BidCheckInput {
  amount: Cents | null;
  minNextBid: Cents;
  state: AuctionState;
  suspended: boolean;
  isSeller: boolean;
}

export type BidCheck =
  | { ok: true }
  | { ok: false; code: "ACCOUNT_SUSPENDED" | "SELF_BIDDING_FORBIDDEN" | "AUCTION_NOT_OPEN" | "BID_BELOW_INCREMENT" | "INVALID_AMOUNT" };

export function checkBid(input: BidCheckInput): BidCheck {
  if (input.suspended) return { ok: false, code: "ACCOUNT_SUSPENDED" };
  if (input.isSeller) return { ok: false, code: "SELF_BIDDING_FORBIDDEN" };
  if (!BIDDABLE.has(input.state)) return { ok: false, code: "AUCTION_NOT_OPEN" };
  if (input.amount === null || input.amount <= 0) return { ok: false, code: "INVALID_AMOUNT" };
  if (input.amount < input.minNextBid) return { ok: false, code: "BID_BELOW_INCREMENT" };
  return { ok: true };
}
