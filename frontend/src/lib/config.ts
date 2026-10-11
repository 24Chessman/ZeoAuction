const env = import.meta.env;

/** Mock mode is the default so every screen works without the Docker stack. */
export const useMocks = (env.VITE_USE_MOCKS ?? "true") !== "false";

export const serviceUrls = {
  auth: env.VITE_AUTH_URL ?? "http://localhost:8001",
  kyc: env.VITE_KYC_URL ?? "http://localhost:8002",
  auction: env.VITE_AUCTION_URL ?? "http://localhost:8003",
  bid: env.VITE_BID_URL ?? "http://localhost:8004",
  payment: env.VITE_PAYMENT_URL ?? "http://localhost:8006",
  ws: env.VITE_WS_URL ?? "ws://localhost:8010/ws",
} as const;

export const featuredAuctionIds: string[] = (
  env.VITE_FEATURED_AUCTIONS ?? "00000000-0000-4000-8000-000000000201"
)
  .split(",")
  .map((id) => id.trim())
  .filter(Boolean);
