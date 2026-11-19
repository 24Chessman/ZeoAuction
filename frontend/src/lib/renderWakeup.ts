/**
 * Render spins down inactive free instances.  These best-effort GET requests are
 * intentionally fire-and-forget: an opaque CORS response or a failed service must
 * never delay or break the user-facing application.
 */
export const renderServiceUrls = [
  "https://zeo-api-gateway.onrender.com",
  "https://zeo-admin-moderation-wuus.onrender.com",
  "https://zeo-auction-orchestrator.onrender.com",
  "https://zeo-auth-user.onrender.com",
  "https://zeo-bid-sf8g.onrender.com",
  "https://zeo-dispute.onrender.com",
  "https://zeo-kyc.onrender.com",
  "https://zeo-payment-escrow.onrender.com",
  "https://zeo-pricing.onrender.com",
  "https://zeo-search-analytics-8fxi.onrender.com",
  "https://zeo-ws-gateway-0kwu.onrender.com",
] as const;

/** Sends a non-blocking request to each deployed Render service. */
export function wakeRenderServices(fetcher: typeof fetch = fetch): void {
  for (const baseUrl of renderServiceUrls) {
    void fetcher(`${baseUrl}/healthz`, {
      method: "GET",
      // Wake the service even if its API does not grant the frontend CORS access.
      mode: "no-cors",
      cache: "no-store",
      // Do not make navigation wait for these requests.
      keepalive: true,
    }).catch(() => {
      // Warming services commonly time out; the application's normal API flow handles retries.
    });
  }
}
