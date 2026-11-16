const env = import.meta.env;

/** Mock mode is the default so every screen works without the Docker stack. */
export const useMocks = (env.ZEO_USE_MOCKS ?? env.VITE_USE_MOCKS ?? "true") !== "false";
const rawApiUrl =
  env.ZEO_API_GATEWAY_URL ??
  env.ZEO_GATEWAY_URL ??
  env.ZEO_API_URL ??
  env.VITE_API_GATEWAY_URL ??
  env.VITE_GATEWAY_URL ??
  env.VITE_API_URL;
const apiUrl = rawApiUrl ? rawApiUrl.replace(/\/+$/, "") : undefined;

export const serviceUrls = {
  auth: env.ZEO_AUTH_URL ?? env.VITE_AUTH_URL ?? apiUrl ?? "http://localhost:8001",
  kyc: env.ZEO_KYC_URL ?? env.VITE_KYC_URL ?? apiUrl ?? "http://localhost:8002",
  auction: env.ZEO_AUCTION_URL ?? env.VITE_AUCTION_URL ?? apiUrl ?? "http://localhost:8003",
  bid: env.ZEO_BID_URL ?? env.VITE_BID_URL ?? apiUrl ?? "http://localhost:8004",
  payment: env.ZEO_PAYMENT_URL ?? env.VITE_PAYMENT_URL ?? apiUrl ?? "http://localhost:8006",
  ws:
    env.ZEO_WS_URL ??
    env.VITE_WS_URL ??
    (apiUrl ? `${apiUrl.replace(/^http/, "ws")}/ws` : "ws://localhost:8010/ws"),
} as const;

export const featuredAuctionIds: string[] = (
  env.ZEO_FEATURED_AUCTIONS ??
  env.VITE_FEATURED_AUCTIONS ??
  "00000000-0000-4000-8000-000000000201"
)
  .split(",")
  .map((id) => id.trim())
  .filter(Boolean);
