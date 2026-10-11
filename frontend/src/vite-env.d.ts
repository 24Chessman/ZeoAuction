/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCKS?: string;
  readonly VITE_AUTH_URL?: string;
  readonly VITE_KYC_URL?: string;
  readonly VITE_AUCTION_URL?: string;
  readonly VITE_BID_URL?: string;
  readonly VITE_PAYMENT_URL?: string;
  readonly VITE_WS_URL?: string;
  readonly VITE_FEATURED_AUCTIONS?: string;
}

declare module "*.yaml?raw" {
  const content: string;
  export default content;
}
