/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly ZEO_USE_MOCKS?: string;
  readonly ZEO_ALLOW_MOCK_SWITCH?: string;
  readonly ZEO_API_URL?: string;
  readonly ZEO_API_GATEWAY_URL?: string;
  readonly ZEO_GATEWAY_URL?: string;
  readonly ZEO_AUTH_URL?: string;
  readonly ZEO_KYC_URL?: string;
  readonly ZEO_AUCTION_URL?: string;
  readonly ZEO_BID_URL?: string;
  readonly ZEO_PAYMENT_URL?: string;
  readonly ZEO_WS_URL?: string;

  readonly VITE_USE_MOCKS?: string;
  readonly VITE_ALLOW_MOCK_SWITCH?: string;
  readonly VITE_API_URL?: string;
  readonly VITE_API_GATEWAY_URL?: string;
  readonly VITE_GATEWAY_URL?: string;
  readonly VITE_AUTH_URL?: string;
  readonly VITE_KYC_URL?: string;
  readonly VITE_AUCTION_URL?: string;
  readonly VITE_BID_URL?: string;
  readonly VITE_PAYMENT_URL?: string;
  readonly VITE_WS_URL?: string;
}

declare module "*.yaml?raw" {
  const content: string;
  export default content;
}
