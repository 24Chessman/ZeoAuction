import { checkBid, minimumNextBid, tierIncrement } from "./bidRules";

describe("bid rules mirror the bid service", () => {
  it("uses the same increment tiers as the CT-3 stub", () => {
    expect(tierIncrement(9_999)).toBe(100);
    expect(tierIncrement(10_000)).toBe(500);
    expect(tierIncrement(49_999)).toBe(500);
    expect(tierIncrement(50_000)).toBe(1_000);
    expect(tierIncrement(100_000)).toBe(2_500);
    expect(tierIncrement(500_000)).toBe(5_000);
    expect(tierIncrement(10_000_000)).toBe(5_000);
  });

  it("starts at the starting price, then leader plus increment", () => {
    expect(minimumNextBid(null, 10_000)).toBe(10_000);
    expect(minimumNextBid(10_500, 10_000)).toBe(11_000);
  });

  const base = { amount: 11_000, minNextBid: 11_000, state: "OPEN" as const, suspended: false, isSeller: false };

  it("accepts a bid at the minimum on an open or extended auction", () => {
    expect(checkBid(base)).toEqual({ ok: true });
    expect(checkBid({ ...base, state: "EXTENDED" })).toEqual({ ok: true });
  });

  it("checks in the service's order: suspended, self-bid, open, increment", () => {
    const everythingWrong = { amount: 1, minNextBid: 11_000, state: "CLOSED" as const, suspended: true, isSeller: true };
    expect(checkBid(everythingWrong)).toEqual({ ok: false, code: "ACCOUNT_SUSPENDED" });
    expect(checkBid({ ...everythingWrong, suspended: false })).toEqual({ ok: false, code: "SELF_BIDDING_FORBIDDEN" });
    expect(checkBid({ ...everythingWrong, suspended: false, isSeller: false })).toEqual({ ok: false, code: "AUCTION_NOT_OPEN" });
    expect(checkBid({ ...base, amount: 10_999 })).toEqual({ ok: false, code: "BID_BELOW_INCREMENT" });
  });

  it("flags a missing amount without inventing a server code", () => {
    expect(checkBid({ ...base, amount: null })).toEqual({ ok: false, code: "INVALID_AMOUNT" });
  });
});
